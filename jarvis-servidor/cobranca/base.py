"""O encaixe da cobrança automática.

Nenhuma regra de negócio sabe qual é o gateway — nem vai saber. O dia em que
você escolher um (Mercado Pago, Asaas, Stripe), o trabalho é escrever uma
classe destas e registrá-la; `assinaturas.py` e as rotas continuam iguais.

Duas responsabilidades, e só:

1. **Falar com o gateway** (criar, cancelar, consultar).
2. **Traduzir** o evento que o gateway manda no webhook para um dos três
   eventos que este sistema entende. O vocabulário de cada gateway fica preso
   dentro da sua própria classe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Os três eventos que mudam alguma coisa aqui. Qualquer gateway, por mais
# barulhento que seja, cabe nestes três.
APROVADO = "pagamento_aprovado"
FALHOU = "pagamento_falhou"
CANCELADA = "assinatura_cancelada"
IGNORADO = "ignorado"


@dataclass
class Evento:
    """O que sobra de um webhook depois de traduzido."""

    tipo: str = IGNORADO
    email: str = ""
    evento_id: str = ""
    dias: int = 30
    referencia: str = ""
    detalhe: str = ""
    bruto: dict = field(default_factory=dict)


class Cobranca:
    """A interface. Quem for implementar, herda daqui e sobrescreve."""

    nome = "base"

    def criar_assinatura(self, usuario_id: int, email: str, plano: str = "base") -> dict:
        """Devolve o que o cliente precisa para pagar (link, QR, o que for)."""
        raise NotImplementedError

    def cancelar(self, usuario_id: int) -> dict:
        raise NotImplementedError

    def consultar(self, usuario_id: int) -> dict:
        raise NotImplementedError

    def traduzir(self, corpo: dict) -> Evento:
        """Do JSON que o gateway mandou para um Evento daqui."""
        raise NotImplementedError
