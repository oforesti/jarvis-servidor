"""Cobrança manual — a que vale hoje.

Não existe gateway nenhum ainda: quem recebe é você, por Pix, e quem libera é
o painel administrativo. Esta classe existe para que o resto do sistema já
converse com uma interface de cobrança desde o primeiro dia, em vez de ganhar
uma no dia da troca.
"""

from __future__ import annotations

from .. import assinaturas, banco
from .base import Cobranca, Evento, IGNORADO


class CobrancaManual(Cobranca):
    nome = "manual"

    def criar_assinatura(self, usuario_id: int, email: str, plano: str = "base") -> dict:
        """Não cria nada: devolve a instrução de pagamento para a tela mostrar."""
        return {
            "modo": "manual",
            "instrucao": "Faça o Pix e me avise; eu libero a sua conta na hora.",
            "situacao": assinaturas.situacao(usuario_id),
        }

    def cancelar(self, usuario_id: int) -> dict:
        return assinaturas.vencer(usuario_id, motivo="cancelada pelo proprio usuario")

    def consultar(self, usuario_id: int) -> dict:
        return assinaturas.situacao(usuario_id)

    def traduzir(self, corpo: dict) -> Evento:
        """Cobrança manual não recebe webhook — se chegar um, é ruído."""
        return Evento(tipo=IGNORADO, bruto=corpo,
                      detalhe="cobranca manual nao processa webhook")
