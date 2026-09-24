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

from . import banco, planos
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


def _normalizar_plano(plano: str, aparelhos: int) -> tuple[str, int]:
    """Plano conhecido e total de equipamentos dentro do teto dele.

    Uma página antiga do site, ainda em cache, manda `base` com o número de
    adicionais; vira Singular, que libera um equipamento só, em vez de um
    pedido que o painel não saberia cobrar. No Supreme o número não importa:
    ele é sem limite, e o pedido guarda 0.
    """
    plano = (plano or "").strip().lower()
    if plano == planos.LEGADO or not plano:
        return planos.PADRAO, 1
    if not (planos.existe(plano) or plano == planos.TESTE):
        raise ErroConta("esse plano não existe", 400, "plano_invalido")
    if planos.ilimitado(plano):
        return plano, 0
    maximo = planos.max_equipamentos(plano)
    total = int(aparelhos or 0)
    if total < 1 or total > maximo:
        faixa = ("1 computador (com o celular)" if maximo == 1
                 else f"de 1 a {maximo} computadores (cada um com o celular)")
        raise ErroConta(f"o plano {planos.nome(plano)} libera {faixa}",
                        400, "equipamentos_invalidos")
    return plano, total


def _conferir_teste(email: str, usuario) -> None:
    """Um teste grátis por pessoa, e só para quem nunca teve a conta liberada.

    Sem isso, bastaria pedir outro teste a cada semana. A recusa diz o
    caminho, em vez de só dizer não.
    """
    ja_testou = banco.um(
        "SELECT id FROM pedidos WHERE email = ? AND plano = ? AND situacao = 'atendido'",
        (email, planos.TESTE))
    ja_ativou = False
    if usuario is not None:
        linha = banco.um("SELECT validade FROM assinaturas WHERE usuario_id = ?",
                         (usuario["id"],))
        ja_ativou = bool(linha and linha["validade"])
    if ja_testou or ja_ativou:
        raise ErroConta(
            "esta conta já usou o teste grátis. Para continuar usando o JARVIS, "
            "escolha um dos planos.", 409, "teste_ja_usado")


def criar(email: str, nome: str = "", telefone: str = "", plano: str = planos.PADRAO,
          aparelhos: int = 1, observacao: str = "", ip: str = "") -> dict:
    email = normalizar_email(email)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ErroConta("esse e-mail não parece válido", 400, "email_invalido")

    if _recentes(email, ip) >= LIMITE_POR_HORA:
        banco.anotar_recusa("pedidos_demais", email=email, ip=ip)
        raise ErroConta(
            "recebi vários pedidos seus agora há pouco. Já estou olhando — "
            "se for urgente, me chame no e-mail.", 429, "pedidos_demais")

    plano, aparelhos = _normalizar_plano(plano, aparelhos)
    usuario = banco.um("SELECT id FROM usuarios WHERE email = ?", (email,))
    if plano == planos.TESTE:
        _conferir_teste(email, usuario)
    aberto = banco.um(
        "SELECT id, plano, aparelhos FROM pedidos WHERE email = ? AND situacao = 'novo'",
        (email,))

    # O servidor roda no PC de casa, que nao fica ligado o dia todo: o aviso
    # por e-mail e o que te alcanca quando voce nao esta na frente do painel.
    from . import aviso_email

    dados = {"email": email, "nome": nome, "telefone": telefone, "plano": plano,
             "aparelhos": aparelhos, "observacao": observacao}

    if aberto:
        # clicou duas vezes, ou mudou de ideia sobre o plano: atualiza em vez
        # de criar outro. O painel não precisa ver a indecisão de ninguém.
        banco.executar(
            "UPDATE pedidos SET plano = ?, aparelhos = ?, observacao = ?, nome = ?, "
            "telefone = ?, quando = ?, usuario_id = COALESCE(?, usuario_id) WHERE id = ?",
            (plano, aparelhos, observacao[:500], nome[:80], telefone[:40],
             banco.agora(), usuario["id"] if usuario else None, aberto["id"]),
        )
        # Mudou o plano ou os equipamentos? Então o e-mail que você recebeu
        # antes está errado — manda o novo. Clique duplo não gera e-mail.
        if (aberto["plano"], aberto["aparelhos"]) != (plano, aparelhos):
            aviso_email.pedido_novo(dados, tem_conta=usuario is not None, alterado=True)
        return {"id": aberto["id"], "repetido": True}

    pedido_id = banco.executar(
        "INSERT INTO pedidos (usuario_id, email, nome, telefone, plano, aparelhos, "
        "observacao, quando, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (usuario["id"] if usuario else None, email, nome[:80], telefone[:40],
         plano, aparelhos, observacao[:500], banco.agora(), ip[:60]),
    )
    aviso_email.pedido_novo(dados, tem_conta=usuario is not None)

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


def atender(pedido_id: int, dias: int | None = None) -> dict:
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

    equipamentos = planos.equipamentos_do_pedido(pedido["plano"], pedido["aparelhos"])
    if dias is None:
        dias = planos.dias_de_liberacao(pedido["plano"])
    assinaturas.ativar(usuario["id"], dias)
    assinaturas.definir_plano(usuario["id"], pedido["plano"], equipamentos)
    banco.executar("UPDATE pedidos SET usuario_id = ?, situacao = 'atendido', "
                   "atendido_em = ? WHERE id = ?",
                   (usuario["id"], banco.agora(), pedido_id))
    return {"usuario_id": usuario["id"], "email": pedido["email"],
            "plano": pedido["plano"], "equipamentos": equipamentos, "dias": dias}
