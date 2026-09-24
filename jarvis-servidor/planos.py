"""Os planos à venda — um lugar só para preço, pessoas e equipamentos.

O site, o e-mail de aviso e o painel leem daqui. Mudar um preço é mudar esta
tabela (e o espelho dela no `index.html` do site, que é estático e não tem
como perguntar ao servidor).

Cada plano tem um teto de equipamentos, cobrado à risca: a pessoa escolhe no
pedido quantos quer liberados (até o teto), e nenhuma conta passa dele — nem
pelo painel, nem trocando de plano. Equipamento além do limite não abre o
Jarvis. `None` no teto é o Supreme: sem limite.
"""

from __future__ import annotations

PLANOS: dict[str, dict] = {
    "singular":  {"nome": "Singular",  "preco": 39.99,  "pessoas": 1,    "max_equipamentos": 1},
    "business":  {"nome": "Business",  "preco": 179.99, "pessoas": 5,    "max_equipamentos": 5},
    "executive": {"nome": "Executive", "preco": 349.99, "pessoas": 10,   "max_equipamentos": 10},
    "supreme":   {"nome": "Supreme",   "preco": 699.99, "pessoas": None, "max_equipamentos": None},
}
PADRAO = "singular"

# "Sem limite" na conta vira este número. O `limite` continua sendo um inteiro
# para o cliente, que compara quantos aparelhos tem com ele; ninguém chega aqui.
SEM_LIMITE = 1000

# O teste grátis não é um plano à venda: é um pedido que você libera por 7
# dias no painel. Quando o prazo acaba, a conta vence como qualquer outra e o
# Jarvis para de abrir até um plano pago ser ativado. Um teste por e-mail, com
# o mesmo equipamento único do Singular.
TESTE = "teste"
TESTE_INFO = {"nome": "Teste grátis", "preco": 0.0, "pessoas": 1, "max_equipamentos": 1}
DIAS_TESTE = 7

# Pedidos e assinaturas de antes dos planos: R$ 39,99 com 1 aparelho incluso
# e R$ 10 por aparelho adicional. Continuam aparecendo certo no painel, com o
# limite que foi liberado para eles.
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


def max_equipamentos(plano: str) -> int | None:
    """Teto do plano; None = sem limite (Supreme) ou plano antigo, sem teto."""
    info = _info(plano)
    return info["max_equipamentos"] if info else None


def ilimitado(plano: str) -> bool:
    info = _info(plano)
    return bool(info) and info["max_equipamentos"] is None


def limite_efetivo(plano: str, liberados: int) -> int:
    """Quantos equipamentos a conta pode ter com acesso, à risca.

    É o número liberado para ela, mas nunca acima do teto do plano: um clique
    a mais no painel ou uma troca de plano não dão mais do que o plano vende.
    """
    if ilimitado(plano):
        return SEM_LIMITE
    teto = max_equipamentos(plano)
    liberados = max(1, int(liberados or 0))
    return liberados if teto is None else min(liberados, teto)


def equipamentos_txt(quantidade: int | None) -> str:
    if quantidade is None or quantidade >= SEM_LIMITE:
        return "sem limite de equipamentos"
    return f"{quantidade} equipamento{'s' if quantidade != 1 else ''}"


def preco(plano: str, extras_legado: int = 0) -> float:
    """Mensalidade. `extras_legado` só conta no plano antigo."""
    if _info(plano):
        return _info(plano)["preco"]
    return LEGADO_PRECO + max(0, extras_legado) * LEGADO_POR_APARELHO


def moeda(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def equipamentos_do_pedido(plano: str, aparelhos: int) -> int | None:
    """Total de equipamentos que o pedido pede; None = sem limite.

    Nos planos novos, `pedidos.aparelhos` já é o total. No antigo era o número
    de adicionais, somado ao aparelho que vinha incluso.
    """
    if ilimitado(plano):
        return None
    if _info(plano):
        return max(1, int(aparelhos or 0))
    return 1 + max(0, int(aparelhos or 0))


def dias_de_liberacao(plano: str) -> int:
    """Quantos dias o botão "Liberar" do pedido dá."""
    return DIAS_TESTE if plano == TESTE else 30
