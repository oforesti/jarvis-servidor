"""As regras: quem é a pessoa, o que ela pagou e quantos aparelhos pode ligar.

As rotas ficam finas de propósito — tudo o que decide alguma coisa mora aqui,
para os testes exercitarem a regra sem passar por HTTP.

Uma separação importante: **entrar** e **ter licença** são coisas diferentes.
Quem está com a assinatura vencida consegue fazer login e ver a própria tela de
conta (senão não teria como descobrir o motivo nem resolver); o que ela não
consegue é usar o Jarvis. Quem decide isso é `estado_da_assinatura`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import banco
from .config import config
from .seguranca import (conferir_senha, criar_acesso, hash_refresh, hash_senha,
                        novo_refresh, senha_fraca)


class ErroConta(Exception):
    """Erro que vira resposta HTTP com mensagem legível em português."""

    def __init__(self, mensagem: str, http: int = 400, motivo: str = "",
                 extra: dict | None = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.http = http
        self.motivo = motivo or "erro"
        self.extra = extra or {}


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


# ===================================================================== conta
def criar_usuario(email: str, senha: str, nome: str = "", ip: str = "") -> dict:
    email = normalizar_email(email)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ErroConta("esse e-mail não parece válido", 400, "email_invalido")
    fraca = senha_fraca(senha)
    if fraca:
        raise ErroConta(fraca, 400, "senha_fraca")
    if banco.um("SELECT id FROM usuarios WHERE email = ?", (email,)):
        banco.anotar_recusa("email_em_uso", email=email, ip=ip)
        raise ErroConta("já existe uma conta com esse e-mail", 409, "email_em_uso")

    agora = banco.agora()
    usuario_id = banco.executar(
        "INSERT INTO usuarios (email, senha_hash, nome, criado_em) VALUES (?, ?, ?, ?)",
        (email, hash_senha(senha), (nome or "").strip()[:80], agora),
    )
    validade = None
    situacao = "vencida"
    if config.dias_de_teste > 0:
        validade = (datetime.now(timezone.utc)
                    + timedelta(days=config.dias_de_teste)).isoformat(timespec="seconds")
        situacao = "ativa"
    banco.executar(
        "INSERT INTO assinaturas (usuario_id, validade, situacao, atualizado_em) "
        "VALUES (?, ?, ?, ?)",
        (usuario_id, validade, situacao, agora),
    )
    return {"id": usuario_id, "email": email}


def autenticar(email: str, senha: str, ip: str = ""):
    email = normalizar_email(email)
    _conferir_forca_bruta(email, ip)

    usuario = banco.um("SELECT * FROM usuarios WHERE email = ?", (email,))
    # Mesma mensagem para e-mail inexistente e senha errada: dizer qual dos
    # dois falhou entrega ao atacante a lista de quem tem conta aqui.
    if usuario is None or not conferir_senha(usuario["senha_hash"], senha):
        banco.anotar_recusa("senha_incorreta", email=email, ip=ip)
        raise ErroConta("e-mail ou senha incorretos", 401, "senha_incorreta")
    if usuario["bloqueado"]:
        banco.anotar_recusa("conta_bloqueada", email=email, ip=ip)
        raise ErroConta(
            "esta conta está bloqueada. Fale comigo para reativar.", 403, "conta_bloqueada")
    return usuario


def _conferir_forca_bruta(email: str, ip: str) -> None:
    """Trava boba, mas que resolve o caso real: script tentando senha em série."""
    desde = (datetime.now(timezone.utc)
             - timedelta(minutes=config.tentativas_janela_min)).isoformat(timespec="seconds")
    linha = banco.um(
        "SELECT COUNT(*) AS n FROM recusas "
        "WHERE motivo = 'senha_incorreta' AND quando > ? AND (email = ? OR (ip <> '' AND ip = ?))",
        (desde, email, ip),
    )
    if linha and linha["n"] >= config.tentativas_max:
        raise ErroConta(
            f"muitas tentativas seguidas. Espere {config.tentativas_janela_min} "
            "minutos e tente de novo.", 429, "forca_bruta")


# ================================================================ assinatura
def estado_da_assinatura(usuario_id: int) -> dict:
    """A verdade sobre a licença, calculada na hora.

    A coluna `situacao` sozinha não serve: uma assinatura marcada 'ativa' com
    validade de ontem está vencida, e ninguém roda tarefa de meia-noite aqui.
    """
    linha = banco.um("SELECT * FROM assinaturas WHERE usuario_id = ?", (usuario_id,))
    if linha is None:
        return {"situacao": "vencida", "validade": None, "aparelhos_pagos": 0,
                "limite": config.aparelhos_inclusos, "plano": "base", "motivo":
                "esta conta ainda não tem assinatura"}

    validade = banco.para_data(linha["validade"])
    situacao = linha["situacao"]
    motivo = ""
    if situacao == "bloqueada":
        motivo = "assinatura bloqueada"
    elif validade is None:
        situacao, motivo = "vencida", "assinatura ainda não foi ativada"
    elif validade < datetime.now(timezone.utc):
        situacao, motivo = "vencida", "assinatura venceu em " + validade.strftime("%d/%m/%Y")
    else:
        situacao = "ativa"

    return {
        "situacao": situacao,
        "validade": linha["validade"],
        "plano": linha["plano"],
        "aparelhos_pagos": linha["aparelhos_pagos"],
        "limite": config.aparelhos_inclusos + linha["aparelhos_pagos"],
        "motivo": motivo,
    }


# ================================================================= aparelhos
def aparelhos_do_usuario(usuario_id: int) -> list[dict]:
    linhas = banco.consultar(
        "SELECT id, apelido, plataforma, criado_em, ultimo_acesso FROM aparelhos "
        "WHERE usuario_id = ? ORDER BY ultimo_acesso DESC",
        (usuario_id,),
    )
    return [dict(l) for l in linhas]


def registrar_aparelho(usuario_id: int, impressao: str, apelido: str,
                       plataforma: str, email: str = "", ip: str = "") -> int:
    """Devolve o id do aparelho, recusando se passar do limite do plano.

    Aparelho já conhecido nunca é recusado — senão baixar o limite deixaria a
    pessoa trancada para fora de uma máquina que ela já usava.
    """
    if not impressao:
        raise ErroConta("não consegui identificar este aparelho", 400, "sem_impressao")

    agora = banco.agora()
    existente = banco.um(
        "SELECT id FROM aparelhos WHERE usuario_id = ? AND impressao = ?",
        (usuario_id, impressao),
    )
    if existente:
        banco.executar(
            "UPDATE aparelhos SET ultimo_acesso = ?, apelido = COALESCE(NULLIF(?, ''), apelido), "
            "plataforma = COALESCE(NULLIF(?, ''), plataforma) WHERE id = ?",
            (agora, (apelido or "").strip()[:60], (plataforma or "").strip()[:30], existente["id"]),
        )
        return existente["id"]

    estado = estado_da_assinatura(usuario_id)
    atuais = banco.um("SELECT COUNT(*) AS n FROM aparelhos WHERE usuario_id = ?",
                      (usuario_id,))["n"]
    if atuais >= estado["limite"]:
        banco.anotar_recusa(
            "limite_de_aparelhos", email=email, impressao=impressao, ip=ip,
            detalhe=f"{atuais} aparelhos, limite {estado['limite']}")
        raise ErroConta(
            f"sua assinatura libera {estado['limite']} aparelho"
            f"{'s' if estado['limite'] > 1 else ''} e você já tem {atuais}. "
            "Remova um aparelho na tela de conta ou contrate um adicional.",
            403, "limite_de_aparelhos",
            extra={"limite": estado["limite"], "aparelhos": aparelhos_do_usuario(usuario_id)},
        )

    return banco.executar(
        "INSERT INTO aparelhos (usuario_id, impressao, apelido, plataforma, criado_em, ultimo_acesso) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (usuario_id, impressao, (apelido or "").strip()[:60],
         (plataforma or "").strip()[:30], agora, agora),
    )


def remover_aparelho(usuario_id: int, aparelho_id: int) -> bool:
    linha = banco.um("SELECT id FROM aparelhos WHERE id = ? AND usuario_id = ?",
                     (aparelho_id, usuario_id))
    if linha is None:
        return False
    # as sessões vão junto pela chave estrangeira, mas revogar explicitamente
    # deixa o rastro de quando o acesso caiu
    banco.executar("UPDATE sessoes SET revogada_em = ? WHERE aparelho_id = ? AND revogada_em IS NULL",
                   (banco.agora(), aparelho_id))
    banco.executar("DELETE FROM aparelhos WHERE id = ?", (aparelho_id,))
    return True


# =================================================================== sessões
def abrir_sessao(usuario_id: int, aparelho_id: int, admin: bool = False) -> dict:
    """Uma sessão por aparelho: entrar de novo derruba a anterior do MESMO aparelho.

    Não mexe nas sessões dos outros aparelhos — quem paga por três tem três.
    """
    agora_txt = banco.agora()
    banco.executar(
        "UPDATE sessoes SET revogada_em = ? WHERE aparelho_id = ? AND revogada_em IS NULL",
        (agora_txt, aparelho_id),
    )
    refresh, refresh_h = novo_refresh()
    expira = (datetime.now(timezone.utc)
              + timedelta(days=config.dias_refresh)).isoformat(timespec="seconds")
    sessao_id = banco.executar(
        "INSERT INTO sessoes (usuario_id, aparelho_id, refresh_hash, criado_em, expira_em) "
        "VALUES (?, ?, ?, ?, ?)",
        (usuario_id, aparelho_id, refresh_h, agora_txt, expira),
    )
    acesso, vida = criar_acesso(usuario_id, aparelho_id, sessao_id, admin)
    return {"acesso": acesso, "expira_em": vida, "refresh": refresh,
            "sessao_id": sessao_id, "aparelho_id": aparelho_id}


def renovar_sessao(refresh: str, ip: str = "") -> dict:
    """Troca o refresh por um par novo. O antigo morre na mesma hora.

    Rotacionar importa: se um refresh vazar e o dono continuar usando o dele, a
    próxima renovação do ladrão falha — e sobra registro da tentativa.
    """
    sessao = banco.um("SELECT * FROM sessoes WHERE refresh_hash = ?", (hash_refresh(refresh),))
    if sessao is None:
        banco.anotar_recusa("refresh_desconhecido", ip=ip)
        raise ErroConta("sua sessão não vale mais — entre de novo", 401, "refresh_desconhecido")
    if sessao["revogada_em"]:
        banco.anotar_recusa("refresh_revogado", ip=ip, detalhe=f"sessao {sessao['id']}")
        raise ErroConta("esta sessão foi encerrada — entre de novo", 401, "refresh_revogado")
    expira = banco.para_data(sessao["expira_em"])
    if expira is None or expira < datetime.now(timezone.utc):
        raise ErroConta("sua sessão expirou — entre de novo", 401, "refresh_expirado")

    usuario = banco.um("SELECT * FROM usuarios WHERE id = ?", (sessao["usuario_id"],))
    if usuario is None or usuario["bloqueado"]:
        raise ErroConta("esta conta está bloqueada", 403, "conta_bloqueada")

    agora_txt = banco.agora()
    banco.executar("UPDATE sessoes SET revogada_em = ? WHERE id = ?", (agora_txt, sessao["id"]))
    banco.executar("UPDATE aparelhos SET ultimo_acesso = ? WHERE id = ?",
                   (agora_txt, sessao["aparelho_id"]))
    return abrir_sessao(sessao["usuario_id"], sessao["aparelho_id"], bool(usuario["admin"]))


def encerrar_sessao(refresh: str) -> bool:
    sessao = banco.um("SELECT id FROM sessoes WHERE refresh_hash = ? AND revogada_em IS NULL",
                      (hash_refresh(refresh),))
    if sessao is None:
        return False
    banco.executar("UPDATE sessoes SET revogada_em = ? WHERE id = ?",
                   (banco.agora(), sessao["id"]))
    return True


def sessao_viva(sessao_id: int) -> bool:
    linha = banco.um("SELECT revogada_em FROM sessoes WHERE id = ?", (sessao_id,))
    return bool(linha) and not linha["revogada_em"]


def resumo_da_conta(usuario_id: int) -> dict:
    usuario = banco.um("SELECT id, email, nome, admin FROM usuarios WHERE id = ?", (usuario_id,))
    if usuario is None:
        raise ErroConta("conta não encontrada", 404, "sem_conta")
    return {
        "email": usuario["email"],
        "nome": usuario["nome"],
        "admin": bool(usuario["admin"]),
        "assinatura": estado_da_assinatura(usuario_id),
        "aparelhos": aparelhos_do_usuario(usuario_id),
        "url_assinatura": config.url_assinatura,
    }
