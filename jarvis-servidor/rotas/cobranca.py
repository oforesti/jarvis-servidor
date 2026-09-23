"""Webhook de cobrança e o que o cliente chama para assinar.

O webhook é genérico: `/webhook/cobranca/{provedor}`. Ele confere a
assinatura, pede ao adaptador daquele provedor para traduzir o corpo, e passa
o resultado adiante. Nenhuma regra de negócio aqui dentro — nem o nome de um
gateway.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Request

from .. import banco, cobranca
from ..contas import ErroConta
from .conta import exigir_token

rotas = APIRouter(tags=["cobranca"])


@rotas.post("/webhook/cobranca/{provedor}")
async def webhook(provedor: str, request: Request,
                  assinatura: str = Header(default="", alias=cobranca.CABECALHO_ASSINATURA)) -> dict:
    corpo = await request.body()
    if not cobranca.conferir_assinatura(corpo, assinatura):
        banco.anotar_recusa("webhook_sem_assinatura", detalhe=provedor[:60])
        raise ErroConta("assinatura do webhook não confere", 401, "webhook_invalido")

    try:
        dados = json.loads(corpo or b"{}")
    except json.JSONDecodeError:
        raise ErroConta("corpo do webhook não é JSON válido", 400, "webhook_ilegivel")

    adaptador = cobranca.obter(provedor)
    evento = adaptador.traduzir(dados if isinstance(dados, dict) else {})
    resultado = cobranca.aplicar(evento, adaptador.nome)
    return {"ok": True, **resultado}


@rotas.post("/cobranca/assinar")
def assinar(token: dict = Depends(exigir_token)) -> dict:
    """O que a tela de conta mostra para quem quer assinar ou renovar."""
    usuario_id = int(token["sub"])
    usuario = banco.um("SELECT email FROM usuarios WHERE id = ?", (usuario_id,))
    adaptador = cobranca.obter()
    return {"ok": True, "provedor": adaptador.nome,
            **adaptador.criar_assinatura(usuario_id, usuario["email"] if usuario else "")}


@rotas.post("/cobranca/cancelar")
def cancelar(token: dict = Depends(exigir_token)) -> dict:
    """Cancelamento pedido pelo próprio usuário."""
    return {"ok": True, "assinatura": cobranca.obter().cancelar(int(token["sub"]))}
