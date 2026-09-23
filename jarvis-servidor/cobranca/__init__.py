"""Registro dos meios de cobrança.

Trocar de gateway é trocar uma variável de ambiente, não mexer em código de
regra de negócio. `JARVIS_LICENCA_COBRANCA=manual` (padrão) ou `simulado`.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from .. import assinaturas, banco
from .base import APROVADO, CANCELADA, Cobranca, Evento, FALHOU, IGNORADO  # noqa: F401
from .manual import CobrancaManual
from .simulado import CobrancaSimulada

CABECALHO_ASSINATURA = "X-Cobranca-Assinatura"

DISPONIVEIS: dict[str, type[Cobranca]] = {
    CobrancaManual.nome: CobrancaManual,
    CobrancaSimulada.nome: CobrancaSimulada,
}


def obter(nome: str = "") -> Cobranca:
    escolhido = (nome or os.getenv("JARVIS_LICENCA_COBRANCA") or "manual").strip().lower()
    return DISPONIVEIS.get(escolhido, CobrancaManual)()


def conferir_assinatura(corpo: bytes, assinatura: str) -> bool:
    """O webhook precisa provar que veio de quem diz que veio.

    Mesma ideia do Elo entre PC e celular: o segredo não viaja, o que viaja é
    um HMAC do corpo. Sem isso, qualquer um que descobrisse a URL ativaria a
    própria assinatura com um curl.
    """
    from ..config import config

    if not assinatura:
        return False
    esperada = hmac.new(config.segredo_webhook.encode("utf-8"), corpo,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, assinatura.strip())


def aplicar(evento: Evento, provedor: str) -> dict:
    """Traduz um evento de cobrança em mudança de estado. É só isso que ele faz.

    Repetição é comum: gateway reenvia webhook quando não recebe 200 rápido.
    Por isso o par (provedor, evento_id) é único no banco — o segundo aviso
    igual não soma mais trinta dias na assinatura de ninguém.
    """
    if evento.tipo == IGNORADO:
        return {"aplicado": False, "motivo": "evento sem efeito aqui"}

    usuario = banco.um("SELECT id, email FROM usuarios WHERE email = ?",
                       ((evento.email or "").strip().lower(),))
    if usuario is None:
        banco.anotar_recusa("webhook_sem_conta", email=evento.email,
                            detalhe=f"{provedor}:{evento.tipo}")
        return {"aplicado": False, "motivo": "não achei conta com esse e-mail"}

    if evento.evento_id:
        repetido = banco.um(
            "SELECT id FROM eventos_cobranca WHERE provedor = ? AND evento_id = ?",
            (provedor, evento.evento_id))
        if repetido:
            return {"aplicado": False, "motivo": "evento repetido, já estava aplicado"}

    if evento.tipo == APROVADO:
        resultado = assinaturas.ativar(usuario["id"], evento.dias, provedor,
                                       evento.referencia)
        acao = f"liberada por {evento.dias} dias"
    elif evento.tipo == CANCELADA:
        resultado = assinaturas.vencer(usuario["id"],
                                       motivo=f"{provedor}: assinatura cancelada")
        acao = "vencida (assinatura cancelada)"
    else:                                     # FALHOU
        resultado = assinaturas.vencer(usuario["id"],
                                       motivo=f"{provedor}: {evento.detalhe or 'pagamento falhou'}")
        acao = "vencida (pagamento não entrou)"

    import json

    banco.executar(
        "INSERT INTO eventos_cobranca (provedor, evento_id, tipo, usuario_id, conteudo, recebido_em) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (provedor, evento.evento_id or banco.agora(), evento.tipo, usuario["id"],
         json.dumps(evento.bruto, ensure_ascii=False)[:4000], banco.agora()),
    )
    return {"aplicado": True, "acao": acao, "assinatura": resultado}
