"""Pedidos de compra vindos do site.

O site é uma página estática hospedada em outro lugar; ele não tem banco nem
sessão. Então o fluxo é o mais simples que resolve: a pessoa se cadastra e
manda um pedido, o pedido aparece no seu painel, e você libera quando o Pix
cair. Nenhum pagamento passa por aqui.

Duas defesas, porque este é o único lugar do sistema aberto para a internet
inteira sem login:

1. **Limite por IP e por e-mail.** Sem isso, um script encheria o painel de
   lixo em dois minutos e você não acharia mais o pedido de verdade.
2. **Pedido repetido não duplica.** Quem clica duas vezes no botão (todo
   mundo clica) continua com um pedido só.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import banco
from .contas import ErroConta, normalizar_email

LIMITE_POR_HORA = 5
JANELA_MINUTOS = 60


def _recentes(email: str, ip: str) -> int:
    desde = (datetime.now(timezone.utc)
             - timedelta(minutes=JANELA_MINUTOS)).isoformat(timespec="seconds")
    linha = banco.um(
        "SELECT COUNT(*) AS n FROM pedidos WHERE quando > ? AND (email = ? OR (ip <> '' AND ip = ?))",
        (desde, email, ip))
    return linha["n"] if linha else 0


def criar(email: str, nome: str = "", telefone: str = "", plano: str = "base",
          aparelhos: int = 0, observacao: str = "", ip: str = "") -> dict:
    email = normalizar_email(email)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ErroConta("esse e-mail não parece válido", 400, "email_invalido")

    if _recentes(email, ip) >= LIMITE_POR_HORA:
        banco.anotar_recusa("pedidos_demais", email=email, ip=ip)
        raise ErroConta(
            "recebi vários pedidos seus agora há pouco. Já estou olhando — "
            "se for urgente, me chame no e-mail.", 429, "pedidos_demais")

    usuario = banco.um("SELECT id FROM usuarios WHERE email = ?", (email,))
    aberto = banco.um(
        "SELECT id FROM pedidos WHERE email = ? AND situacao = 'novo'", (email,))

    aparelhos = max(0, min(20, int(aparelhos or 0)))
    if aberto:
        # clicou duas vezes, ou mudou de ideia sobre o plano: atualiza em vez
        # de criar outro. O painel não precisa ver a indecisão de ninguém.
        banco.executar(
            "UPDATE pedidos SET plano = ?, aparelhos = ?, observacao = ?, nome = ?, "
            "telefone = ?, quando = ?, usuario_id = COALESCE(?, usuario_id) WHERE id = ?",
            (plano, aparelhos, observacao[:500], nome[:80], telefone[:40],
             banco.agora(), usuario["id"] if usuario else None, aberto["id"]),
        )
        return {"id": aberto["id"], "repetido": True}

    pedido_id = banco.executar(
        "INSERT INTO pedidos (usuario_id, email, nome, telefone, plano, aparelhos, "
        "observacao, quando, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (usuario["id"] if usuario else None, email, nome[:80], telefone[:40],
         plano, aparelhos, observacao[:500], banco.agora(), ip[:60]),
    )

    # O servidor roda no PC de casa, que nao fica ligado o dia todo: o aviso
    # por e-mail e o que te alcanca quando voce nao esta na frente do painel.
    from . import aviso_email

    aviso_email.pedido_novo(
        {"email": email, "nome": nome, "telefone": telefone, "plano": plano,
         "aparelhos": aparelhos, "observacao": observacao},
        tem_conta=usuario is not None)

    return {"id": pedido_id, "repetido": False}


def vincular_conta(usuario_id: int, email: str) -> None:
    """Chamado quando alguém cria a conta depois de ter pedido."""
    banco.executar(
        "UPDATE pedidos SET usuario_id = ? WHERE email = ? AND usuario_id IS NULL",
        (usuario_id, normalizar_email(email)))


def listar(situacao: str = "novo", limite: int = 100) -> list[dict]:
    if situacao == "todos":
        linhas = banco.consultar(
            "SELECT * FROM pedidos ORDER BY situacao = 'novo' DESC, id DESC LIMIT ?",
            (limite,))
    else:
        linhas = banco.consultar(
            "SELECT * FROM pedidos WHERE situacao = ? ORDER BY id DESC LIMIT ?",
            (situacao, limite))
    return [dict(l) for l in linhas]


def quantos_novos() -> int:
    linha = banco.um("SELECT COUNT(*) AS n FROM pedidos WHERE situacao = 'novo'")
    return linha["n"] if linha else 0


def marcar(pedido_id: int, situacao: str) -> bool:
    if situacao not in ("novo", "atendido", "recusado"):
        return False
    banco.executar(
        "UPDATE pedidos SET situacao = ?, atendido_em = ? WHERE id = ?",
        (situacao, banco.agora() if situacao != "novo" else None, pedido_id))
    return True


def atender(pedido_id: int, dias: int = 30) -> dict:
    """Libera a conta do pedido e marca ele como resolvido, de uma vez só.

    É o caminho de todo dia: o Pix caiu, um clique. Se a pessoa ainda não
    criou a conta, não dá para liberar nada — e a resposta diz isso, em vez
    de fingir que deu certo.
    """
    from . import assinaturas

    pedido = banco.um("SELECT * FROM pedidos WHERE id = ?", (pedido_id,))
    if pedido is None:
        raise ErroConta("esse pedido não existe", 404, "pedido_inexistente")

    usuario = banco.um("SELECT id FROM usuarios WHERE email = ?", (pedido["email"],))
    if usuario is None:
        raise ErroConta(
            f"{pedido['email']} ainda não criou a conta no Jarvis — sem conta não "
            "há o que liberar. Avise a pessoa para se cadastrar primeiro.",
            400, "sem_conta")

    assinaturas.ativar(usuario["id"], dias)
    if pedido["aparelhos"]:
        assinaturas.definir_aparelhos_pagos(usuario["id"], pedido["aparelhos"])
    banco.executar("UPDATE pedidos SET usuario_id = ?, situacao = 'atendido', "
                   "atendido_em = ? WHERE id = ?",
                   (usuario["id"], banco.agora(), pedido_id))
    return {"usuario_id": usuario["id"], "email": pedido["email"],
            "aparelhos": pedido["aparelhos"]}
