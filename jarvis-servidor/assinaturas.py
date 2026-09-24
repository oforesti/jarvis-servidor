"""O estado da assinatura — e os únicos caminhos para mudá-lo.

Tudo que altera uma assinatura passa por aqui: o painel administrativo, o
webhook de cobrança e, um dia, o gateway. Nenhuma dessas funções sabe o nome
de gateway nenhum, de propósito: quando você escolher um, ele traduz os
eventos dele para estas chamadas e mais nada muda.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import banco, planos


def _assinatura(usuario_id: int):
    linha = banco.um("SELECT * FROM assinaturas WHERE usuario_id = ?", (usuario_id,))
    if linha is None:
        banco.executar(
            "INSERT INTO assinaturas (usuario_id, plano, atualizado_em) VALUES (?, ?, ?)",
            (usuario_id, planos.PADRAO, banco.agora()))
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
    """Equipamentos liberados além do que já vem incluso na conta.

    O limite é cobrado à risca: baixar este número tira o acesso dos
    equipamentos que passam do novo limite (os que entraram por último) na
    próxima validação da licença. A pessoa escolhe qual continua removendo os
    outros na tela de conta.
    """
    _assinatura(usuario_id)
    banco.executar(
        "UPDATE assinaturas SET aparelhos_pagos = ?, atualizado_em = ? WHERE usuario_id = ?",
        (max(0, int(quantidade)), banco.agora(), usuario_id))
    return situacao(usuario_id)


def definir_plano(usuario_id: int, plano: str, equipamentos: int | None = None) -> dict:
    """Troca o plano e, se vier, o total de equipamentos liberados.

    Nunca acima do teto do novo plano. Sem o total, mantém o que estava
    liberado, cortado no teto: descer de Executive para Business deixa 5, não
    10. O total é guardado como adicionais sobre o que já vem incluso, que é
    como o limite sempre foi calculado.
    """
    from .config import config

    atual = _assinatura(usuario_id)
    banco.executar(
        "UPDATE assinaturas SET plano = ?, atualizado_em = ? WHERE usuario_id = ?",
        (plano, banco.agora(), usuario_id))
    teto = planos.max_equipamentos(plano)
    if equipamentos is None and teto is not None:
        liberados = config.aparelhos_inclusos + atual["aparelhos_pagos"]
        if liberados > teto:
            equipamentos = teto
    if equipamentos is not None:
        total = int(equipamentos) if teto is None else min(int(equipamentos), teto)
        definir_aparelhos_pagos(usuario_id, total - config.aparelhos_inclusos)
    return situacao(usuario_id)


def situacao(usuario_id: int) -> dict:
    from .contas import estado_da_assinatura

    return estado_da_assinatura(usuario_id)
