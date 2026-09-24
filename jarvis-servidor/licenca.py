"""A resposta que o cliente obedece: pode funcionar, ou não, e por quê.

O cliente pergunta ao abrir e de tempos em tempos. Quando está sem internet,
ele usa o último bloco assinado que recebeu — e é por isso que ele é assinado:
o prazo da folga é decidido aqui, não lá.

O detalhe que fecha a brecha óbvia: a folga **nunca ultrapassa a validade da
assinatura**. Se ela vence amanhã, o bloco vale até amanhã, não por sete dias.
Senão bastaria pedir uma validação na véspera do vencimento e ficar offline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import banco, contas, planos
from .config import config
from .seguranca import assinar_licenca

VERSAO_BLOCO = 1


def _menor(a: datetime, b: datetime) -> datetime:
    return a if a < b else b


def validar(usuario_id: int, aparelho_id: int, ip: str = "") -> dict:
    """Situação completa da licença, pronta para virar tela.

    Devolve sempre 200 no HTTP: isto é uma consulta de estado, não uma ação
    recusada. Quem bloqueia é o cliente, lendo `liberado`.
    """
    estado = contas.estado_da_assinatura(usuario_id)
    usuario = banco.um("SELECT email, bloqueado FROM usuarios WHERE id = ?", (usuario_id,))
    email = usuario["email"] if usuario else ""

    if usuario is None or usuario["bloqueado"]:
        return _negado(usuario_id, "conta_bloqueada",
                       "esta conta está bloqueada", estado, email, ip)

    aparelho = banco.um(
        "SELECT id, apelido FROM aparelhos WHERE id = ? AND usuario_id = ?",
        (aparelho_id, usuario_id))
    if aparelho is None:
        # aconteceu de verdade quando o aparelho foi removido na tela de conta
        # do outro lado: o token ainda existe, o aparelho não
        return _negado(usuario_id, "aparelho_removido",
                       "este aparelho foi desconectado da sua conta", estado, email, ip)

    if estado["situacao"] != "ativa":
        return _negado(usuario_id, estado["situacao"],
                       estado["motivo"] or "assinatura sem validade", estado, email, ip)

    # o limite do plano, à risca: equipamento além dele não abre o Jarvis,
    # nem os que já estavam ligados quando o limite desceu
    if aparelho_id in contas.fora_do_limite(usuario_id, estado["computadores"]):
        ligados = contas.aparelhos_do_usuario(usuario_id)
        return _negado(
            usuario_id, "limite_de_aparelhos",
            f"seu plano libera {planos.equipamentos_txt(estado['computadores'])}, e este "
            "equipamento passou do limite. Remova outro na tela de conta para liberar "
            "este, ou mude para um plano maior.",
            estado, email, ip, extra={"limite": estado["limite"], "aparelhos": ligados})

    validade = banco.para_data(estado["validade"])
    agora = datetime.now(timezone.utc)
    vale_ate = _menor(validade, agora + timedelta(days=config.dias_folga))

    bloco = assinar_licenca({
        "versao": VERSAO_BLOCO,
        "usuario": usuario_id,
        "aparelho": aparelho_id,
        "email": email,
        "vale_ate": vale_ate.isoformat(timespec="seconds"),
        "validade": estado["validade"],
        "emitido_em": agora.isoformat(timespec="seconds"),
    })

    banco.executar("UPDATE aparelhos SET ultimo_acesso = ? WHERE id = ?",
                   (banco.agora(), aparelho_id))

    return {
        "liberado": True,
        "motivo": "",
        "assinatura": estado,
        "aparelho": {"id": aparelho["id"], "apelido": aparelho["apelido"]},
        "bloco": bloco,
        "vale_ate": vale_ate.isoformat(timespec="seconds"),
        "dias_de_folga": config.dias_folga,
        "url_assinatura": config.url_assinatura,
    }


def _negado(usuario_id: int, motivo: str, texto: str, estado: dict,
            email: str, ip: str, extra: dict | None = None) -> dict:
    """Recusa registrada e explicada — sem bloco assinado, que é o que trava.

    Sem `bloco`, o cliente não tem o que guardar: no próximo boot offline ele
    cai no bloco antigo, que expira, e aí bloqueia sozinho.
    """
    banco.anotar_recusa("licenca_" + motivo, email=email, ip=ip,
                        detalhe=f"usuario {usuario_id}")
    return {
        "liberado": False,
        "motivo": motivo,
        "explicacao": texto,
        "assinatura": estado,
        "bloco": "",
        "url_assinatura": config.url_assinatura,
        **(extra or {}),
    }
