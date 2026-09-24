"""Rotas de conta: criar, entrar, renovar, sair e ver os aparelhos.

Finas de propósito. Tudo que decide alguma coisa está em `contas.py`; aqui só
se traduz HTTP para chamada de função e de volta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from .. import acessos, banco, contas
from ..seguranca import impressao_hash, ler_acesso

rotas = APIRouter(prefix="/conta", tags=["conta"])


# ------------------------------------------------------------------ entrada
class DadosAparelho(BaseModel):
    impressao: str = Field(default="", max_length=200)
    apelido: str = Field(default="", max_length=60)
    plataforma: str = Field(default="", max_length=30)


class DadosCriar(DadosAparelho):
    email: str = Field(max_length=200)
    senha: str = Field(max_length=200)
    nome: str = Field(default="", max_length=80)


class DadosEntrar(DadosAparelho):
    email: str = Field(max_length=200)
    senha: str = Field(max_length=200)


class DadosRefresh(BaseModel):
    refresh: str = Field(max_length=400)


def ip_de(request: Request) -> str:
    """Atrás de um PaaS, `request.client.host` é o proxy — o real vem no cabeçalho."""
    encaminhado = request.headers.get("x-forwarded-for", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else ""


# ------------------------------------------------------------ autenticação
def exigir_token(autorizacao: str = Header(default="", alias="Authorization")) -> dict:
    """Dependência das rotas que exigem estar logado.

    Confere a assinatura do JWT **e** se a sessão continua viva: sem a segunda
    parte, desconectar um aparelho não teria efeito nenhum até o token expirar.
    """
    token = autorizacao[7:].strip() if autorizacao.lower().startswith("bearer ") else ""
    dados = ler_acesso(token) if token else None
    if not dados:
        raise contas.ErroConta("faça login de novo", 401, "token_invalido")
    if not contas.sessao_viva(int(dados.get("ses", 0))):
        raise contas.ErroConta("esta sessão foi encerrada — entre de novo", 401, "sessao_revogada")
    return dados


# ---------------------------------------------------------------- as rotas
@rotas.post("/criar")
def criar(dados: DadosCriar, request: Request) -> dict:
    ip = ip_de(request)
    usuario = contas.criar_usuario(dados.email, dados.senha, dados.nome, ip)
    aparelho_id = contas.registrar_aparelho(
        usuario["id"], impressao_hash(dados.impressao), dados.apelido,
        dados.plataforma, usuario["email"], ip)
    sessao = contas.abrir_sessao(usuario["id"], aparelho_id)
    return {"ok": True, **sessao, "conta": contas.resumo_da_conta(usuario["id"])}


@rotas.post("/entrar")
def entrar(dados: DadosEntrar, request: Request) -> dict:
    ip = ip_de(request)
    usuario = contas.autenticar(dados.email, dados.senha, ip)
    aparelho_id = contas.registrar_aparelho(
        usuario["id"], impressao_hash(dados.impressao), dados.apelido,
        dados.plataforma, usuario["email"], ip)
    acessos.registrar(usuario["id"], aparelho_id, ip)
    sessao = contas.abrir_sessao(usuario["id"], aparelho_id, bool(usuario["admin"]))
    return {"ok": True, **sessao, "conta": contas.resumo_da_conta(usuario["id"])}


@rotas.post("/renovar")
def renovar(dados: DadosRefresh, request: Request) -> dict:
    sessao = contas.renovar_sessao(dados.refresh, ip_de(request))
    linha = banco.um("SELECT usuario_id FROM sessoes WHERE id = ?", (sessao["sessao_id"],))
    return {"ok": True, **sessao,
            "conta": contas.resumo_da_conta(linha["usuario_id"]) if linha else {}}


@rotas.post("/sair")
def sair(dados: DadosRefresh) -> dict:
    return {"ok": contas.encerrar_sessao(dados.refresh)}


@rotas.get("")
def ver(token: dict = Depends(exigir_token)) -> dict:
    return {"ok": True, "conta": contas.resumo_da_conta(int(token["sub"]))}


@rotas.get("/aparelhos")
def listar_aparelhos(token: dict = Depends(exigir_token)) -> dict:
    usuario_id = int(token["sub"])
    estado = contas.estado_da_assinatura(usuario_id)
    return {"ok": True, "aparelhos": contas.aparelhos_do_usuario(usuario_id),
            "este": token.get("apa"), "limite": estado["limite"],
            "computadores": estado["computadores"], "celulares": estado["celulares"],
            "ilimitado": estado["ilimitado"]}


@rotas.delete("/aparelhos/{aparelho_id}")
def desconectar_aparelho(aparelho_id: int, token: dict = Depends(exigir_token)) -> dict:
    usuario_id = int(token["sub"])
    if not contas.remover_aparelho(usuario_id, aparelho_id):
        raise contas.ErroConta("esse aparelho não está na sua conta", 404, "aparelho_inexistente")
    return {"ok": True, "aparelhos": contas.aparelhos_do_usuario(usuario_id)}
