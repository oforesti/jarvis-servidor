"""A rota que o Jarvis chama ao abrir e a cada poucas horas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import acessos, licenca
from ..seguranca import chave_publica
from .conta import exigir_token, ip_de

rotas = APIRouter(prefix="/licenca", tags=["licenca"])


@rotas.post("/validar")
def validar(request: Request, token: dict = Depends(exigir_token)) -> dict:
    """Pode funcionar? Responde sempre 200 — quem lê `liberado` é o cliente.

    Um 403 aqui seria pior: o cliente precisa da resposta completa (motivo,
    validade, link para assinar) justamente no caso em que está bloqueado.
    """
    ip = ip_de(request)
    acessos.registrar(int(token["sub"]), int(token.get("apa", 0)), ip)
    resposta = licenca.validar(int(token["sub"]), int(token.get("apa", 0)), ip)
    return {"ok": True, **resposta}


@rotas.get("/chave-publica")
def publica() -> dict:
    """Mesma chave de /chave-publica, aqui para o cliente achar junto do resto."""
    return {"chave": chave_publica()}
