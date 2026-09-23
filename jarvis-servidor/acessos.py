"""De onde cada conta se conecta — e o bloqueio manual de um IP.

Para que isto serve, com honestidade: **investigar**, não punir sozinho.

IP não identifica pessoa. O mesmo cliente honesto aparece com vários num dia
só: o roteador de casa troca de IP, o celular muda de antena no 4G, o Wi-Fi da
escola é outro. E o contrário também acontece — duas pessoas na mesma operadora
móvel podem sair pelo MESMO IP, porque as operadoras compartilham endereço
entre milhares de assinantes.

Por isso a regra que vale continua sendo o limite de aparelhos, que usa a
impressão digital da máquina e não o IP. Esta tela é para você olhar quando
desconfiar de alguma coisa, ver o desenho do uso, e decidir com a mão.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import banco


def registrar(usuario_id: int, aparelho_id: int | None, ip: str) -> None:
    """Uma linha por (aparelho, IP), com contagem. Nunca levanta exceção:
    auditoria não pode derrubar a resposta que ela está auditando."""
    ip = (ip or "").strip()[:60]
    if not ip:
        return
    agora = banco.agora()
    try:
        # `IS ?` (comparação segura com nulo) só existe no SQLite; decidir
        # aqui vale nos dois bancos e ainda se lê melhor
        if aparelho_id is None:
            existente = banco.um(
                "SELECT id, vezes FROM acessos WHERE aparelho_id IS NULL AND ip = ?",
                (ip,))
        else:
            existente = banco.um(
                "SELECT id, vezes FROM acessos WHERE aparelho_id = ? AND ip = ?",
                (aparelho_id, ip))
        if existente:
            banco.executar("UPDATE acessos SET ultimo = ?, vezes = ? WHERE id = ?",
                           (agora, existente["vezes"] + 1, existente["id"]))
        else:
            banco.executar(
                "INSERT INTO acessos (usuario_id, aparelho_id, ip, primeiro, ultimo) "
                "VALUES (?, ?, ?, ?, ?)",
                (usuario_id, aparelho_id, ip, agora, agora))
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------- bloqueio
def bloqueado(ip: str) -> bool:
    if not ip:
        return False
    return banco.um("SELECT ip FROM ips_bloqueados WHERE ip = ?", (ip.strip(),)) is not None


def bloquear(ip: str, motivo: str = "", por: str = "") -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False
    # `INSERT OR REPLACE` é do SQLite. Apagar antes de inserir dá o mesmo
    # resultado e funciona nos dois bancos.
    banco.executar("DELETE FROM ips_bloqueados WHERE ip = ?", (ip,))
    banco.executar(
        "INSERT INTO ips_bloqueados (ip, motivo, quando, por) VALUES (?, ?, ?, ?)",
        (ip, motivo[:200], banco.agora(), por[:120]))
    return True


def liberar(ip: str) -> bool:
    banco.executar("DELETE FROM ips_bloqueados WHERE ip = ?", ((ip or "").strip(),))
    return True


def lista_bloqueados() -> list[dict]:
    return [dict(l) for l in banco.consultar(
        "SELECT * FROM ips_bloqueados ORDER BY quando DESC LIMIT 200")]


# ---------------------------------------------------------------- leitura
def por_conta(dias: int = 30) -> list[dict]:
    """O resumo que a aba mostra: aparelhos, limite e IPs de cada conta.

    `ips_demais` é só um chamariz visual, não um veredito: conta com muitos
    IPs distintos merece um olhar, e nada além disso.
    """
    from .contas import estado_da_assinatura

    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds")
    saida = []
    for u in banco.consultar("SELECT id, email, bloqueado FROM usuarios ORDER BY id DESC LIMIT 300"):
        aparelhos = banco.consultar(
            "SELECT id, apelido, plataforma, ultimo_acesso FROM aparelhos "
            "WHERE usuario_id = ? ORDER BY ultimo_acesso DESC", (u["id"],))
        linhas = banco.consultar(
            "SELECT aparelho_id, ip, ultimo, vezes FROM acessos "
            "WHERE usuario_id = ? AND ultimo > ? ORDER BY ultimo DESC LIMIT 60",
            (u["id"], desde))
        if not aparelhos and not linhas:
            continue

        estado = estado_da_assinatura(u["id"])
        ips = {l["ip"] for l in linhas}
        por_aparelho: dict[int | None, list[dict]] = {}
        for l in linhas:
            por_aparelho.setdefault(l["aparelho_id"], []).append(dict(l))

        saida.append({
            "usuario_id": u["id"],
            "email": u["email"],
            "bloqueada": bool(u["bloqueado"]),
            "situacao": estado["situacao"],
            "limite": estado["limite"],
            "aparelhos": [dict(a) for a in aparelhos],
            "ips": sorted(ips),
            "quantos_ips": len(ips),
            "por_aparelho": por_aparelho,
            # três IPs por aparelho já é bastante para uso normal; acima disso
            # vale o seu olhar, não um bloqueio automático
            "ips_demais": len(ips) > max(3, len(aparelhos) * 3),
        })
    saida.sort(key=lambda c: (not c["ips_demais"], -c["quantos_ips"]))
    return saida
