"""Gateway de mentira, para você testar tudo sem conta em lugar nenhum.

Ele aceita os três eventos que importam — aprovado, falhou, cancelada — no
formato mais parecido possível com o de um gateway de verdade: um `type` e um
`data` aninhado. Assim o caminho que o webhook percorre nos testes é o mesmo
que um Mercado Pago da vida vai percorrer.

Ligar: `JARVIS_LICENCA_COBRANCA=simulado`.
"""

from __future__ import annotations

from .. import assinaturas
from .base import APROVADO, CANCELADA, Cobranca, Evento, FALHOU, IGNORADO

# vocabulário "do gateway" -> vocabulário daqui
TRADUCAO = {
    "payment.approved": APROVADO,
    "pagamento.aprovado": APROVADO,
    "payment.failed": FALHOU,
    "pagamento.falhou": FALHOU,
    "subscription.cancelled": CANCELADA,
    "assinatura.cancelada": CANCELADA,
}


class CobrancaSimulada(Cobranca):
    nome = "simulado"

    def criar_assinatura(self, usuario_id: int, email: str, plano: str = "base") -> dict:
        return {
            "modo": "simulado",
            "link": f"https://gateway-de-mentira.local/pagar/{usuario_id}",
            "situacao": assinaturas.situacao(usuario_id),
        }

    def cancelar(self, usuario_id: int) -> dict:
        return assinaturas.vencer(usuario_id, motivo="cancelada no gateway simulado")

    def consultar(self, usuario_id: int) -> dict:
        return assinaturas.situacao(usuario_id)

    def traduzir(self, corpo: dict) -> Evento:
        dados = corpo.get("data") or {}
        tipo = TRADUCAO.get(str(corpo.get("type") or corpo.get("tipo") or ""), IGNORADO)
        return Evento(
            tipo=tipo,
            email=str(dados.get("email") or corpo.get("email") or ""),
            evento_id=str(corpo.get("id") or dados.get("id") or ""),
            dias=int(dados.get("dias") or 30),
            referencia=str(dados.get("assinatura") or ""),
            detalhe=str(dados.get("motivo") or ""),
            bruto=corpo,
        )
