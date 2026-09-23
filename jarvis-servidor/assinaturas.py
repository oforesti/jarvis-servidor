"""O estado da assinatura — e os únicos caminhos para mudá-lo.

Tudo que altera uma assinatura passa por aqui: o painel administrativo, o
webhook de cobrança e, um dia, o gateway. Nenhuma dessas funções sabe o nome
de gateway nenhum, de propósito: quando você escolher um, ele traduz os
eventos dele para estas chamadas e mais nada muda.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import banco


def _assinatura(usuario_id: int):
    linha = banco.um("SELECT * FROM assinaturas WHERE usuario_id = ?", (usuario_id,))
    if linha is None:
        banco.executar(
            "INSERT INTO assinaturas (usuario_id, atualizado_em) VALUES (?, ?)",
            (usuario_id, banco.agora()))
        linha = banco.um("SELECT * FROM assinaturas WHERE usuario_id = ?", (usuario_id,))
    return linha


def ativar(usuario_id: int, dias: int = 30, provedor: str = "manual",
           referencia: str = "") -> dict:
    """Libera por N dias a partir de hoje.

    Quem já está em dia não perde o que sobrava: renovar antes do vencimento
    soma. Quem estava vencido começa de hoje — não faz sentido pagar hoje e
    receber crédito retroativo.
    """
    atual = _assinatura(usuario_id)
    agora = datetime.now(timezone.utc)
    validade_atual = banco.para_data(atual["validade"])
    base = validade_atual if (validade_atual and validade_atual > agora) else agora
    nova = base + timedelta(days=int(dias))

    banco.executar(
        "UPDATE assinaturas SET situacao = 'ativa', validade = ?, provedor = ?, "
        "referencia_externa = COALESCE(NULLIF(?, ''), referencia_externa), "
        "atualizado_em = ? WHERE usuario_id = ?",
        (nova.isoformat(timespec="seconds"), provedor, referencia,
         banco.agora(), usuario_id),
    )
    return situacao(usuario_id)


def renovar(usuario_id: int, dias: int = 30) -> dict:
    return ativar(usuario_id, dias, provedor=_assinatura(usuario_id)["provedor"])


def vencer(usuario_id: int, motivo: str = "") -> dict:
    """Deixa a assinatura vencer agora — o caso de pagamento que não entrou.

    Diferente de bloquear: vencida volta sozinha se a pessoa pagar; bloqueada
    é decisão minha e só eu desfaço.
    """
    banco.executar(
        "UPDATE assinaturas SET situacao = 'vencida', validade = ?, atualizado_em = ? "
        "WHERE usuario_id = ?",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
         banco.agora(), usuario_id),
    )
    if motivo:
        banco.anotar_recusa("assinatura_vencida", detalhe=motivo[:200])
    return situacao(usuario_id)


def bloquear(usuario_id: int, motivo: str = "") -> dict:
    _assinatura(usuario_id)
    banco.executar(
        "UPDATE assinaturas SET situacao = 'bloqueada', atualizado_em = ? WHERE usuario_id = ?",
        (banco.agora(), usuario_id))
    banco.executar("UPDATE usuarios SET bloqueado = 1 WHERE id = ?", (usuario_id,))
    # derruba as sessões abertas: bloquear e deixar continuar usando até o
    # token expirar seria bloquear pela metade
    banco.executar(
        "UPDATE sessoes SET revogada_em = ? WHERE usuario_id = ? AND revogada_em IS NULL",
        (banco.agora(), usuario_id))
    if motivo:
        banco.anotar_recusa("conta_bloqueada_admin", detalhe=motivo[:200])
    return situacao(usuario_id)


def desbloquear(usuario_id: int) -> dict:
    atual = _assinatura(usuario_id)
    validade = banco.para_data(atual["validade"])
    nova_situacao = "ativa" if validade and validade > datetime.now(timezone.utc) else "vencida"
    banco.executar(
        "UPDATE assinaturas SET situacao = ?, atualizado_em = ? WHERE usuario_id = ?",
        (nova_situacao, banco.agora(), usuario_id))
    banco.executar("UPDATE usuarios SET bloqueado = 0 WHERE id = ?", (usuario_id,))
    return situacao(usuario_id)


def definir_aparelhos_pagos(usuario_id: int, quantidade: int) -> dict:
    """Aparelhos ADICIONAIS pagos, além do que o plano base já inclui.

    Baixar este número nunca desconecta ninguém: quem já está ligado continua,
    e o limite só volta a morder no próximo aparelho novo. Desconectar alguém
    sozinho, por causa de uma mudança de plano, daria suporte no domingo.
    """
    _assinatura(usuario_id)
    banco.executar(
        "UPDATE assinaturas SET aparelhos_pagos = ?, atualizado_em = ? WHERE usuario_id = ?",
        (max(0, int(quantidade)), banco.agora(), usuario_id))
    return situacao(usuario_id)


def situacao(usuario_id: int) -> dict:
    from .contas import estado_da_assinatura

    return estado_da_assinatura(usuario_id)
