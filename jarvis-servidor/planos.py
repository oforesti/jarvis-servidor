"""Os planos à venda — um lugar só para preço, pessoas e equipamentos.

O site, o e-mail de aviso e o painel leem daqui. Mudar um preço é mudar esta
tabela (e o espelho dela no `index.html` do site, que é estático e não tem
como perguntar ao servidor).

`pessoas` é quantas pessoas o plano cobre (None = sem limite). Quem de fato
trava o uso é o número de **equipamentos** liberados, que a pessoa escolhe no
pedido, dentro do máximo do plano.
"""

from __future__ import annotations

PLANOS: dict[str, dict] = {
    "singular":  {"nome": "Singular",  "preco": 39.99,  "pessoas": 1,    "max_equipamentos": 3},
    "business":  {"nome": "Business",  "preco": 179.99, "pessoas": 5,    "max_equipamentos": 15},
    "executive": {"nome": "Executive", "preco": 349.99, "pessoas": 10,   "max_equipamentos": 30},
    "supreme":   {"nome": "Supreme",   "preco": 699.99, "pessoas": None, "max_equipamentos": 100},
}
PADRAO = "singular"

# O teste grátis não é um plano à venda: é um pedido que você libera por 7
# dias no painel. Quando o prazo acaba, a conta vence como qualquer outra e o
# Jarvis para de abrir até um plano pago ser ativado. Um teste por e-mail.
TESTE = "teste"
TESTE_INFO = {"nome": "Teste grátis", "preco": 0.0, "pessoas": 1, "max_equipamentos": 2}
DIAS_TESTE = 7

# Pedidos e assinaturas de antes dos planos: R$ 39,99 com 1 aparelho incluso
# e R$ 10 por aparelho adicional. Continuam aparecendo certo no painel.
LEGADO = "base"
LEGADO_PRECO = 39.99
LEGADO_POR_APARELHO = 10.00


def existe(plano: str) -> bool:
    """Plano pago que pode ser vendido ou atribuído no painel."""
    return plano in PLANOS


def _info(plano: str) -> dict | None:
    if plano == TESTE:
        return TESTE_INFO
    return PLANOS.get(plano)


def nome(plano: str) -> str:
    if _info(plano):
        return _info(plano)["nome"]
    return "Assinatura (antiga)" if plano == LEGADO else (plano or "—")


def pessoas_txt(plano: str) -> str:
    if not _info(plano):
        return "1 pessoa"
    n = _info(plano)["pessoas"]
    if n is None:
        return "sem limite de pessoas"
    return f"até {n} pessoa{'s' if n != 1 else ''}"


def max_equipamentos(plano: str) -> int:
    return (_info(plano) or PLANOS[PADRAO])["max_equipamentos"]


def preco(plano: str, extras_legado: int = 0) -> float:
    """Mensalidade. `extras_legado` só conta no plano antigo."""
    if _info(plano):
        return _info(plano)["preco"]
    return LEGADO_PRECO + max(0, extras_legado) * LEGADO_POR_APARELHO


def moeda(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def equipamentos_do_pedido(plano: str, aparelhos: int) -> int:
    """Total de equipamentos que o pedido pede.

    Nos planos novos, `pedidos.aparelhos` já é o total. No antigo era o número
    de adicionais, somado ao aparelho que vinha incluso.
    """
    if _info(plano):
        return max(1, int(aparelhos or 0))
    return 1 + max(0, int(aparelhos or 0))


def dias_de_liberacao(plano: str) -> int:
    """Quantos dias o botão "Liberar" do pedido dá."""
    return DIAS_TESTE if plano == TESTE else 30
