"""As duas rotas que o site usa: criar conta e pedir a compra.

São as únicas abertas para a internet inteira sem login, então elas fazem
pouca coisa de propósito: criam a conta (sem sessão, sem aparelho) e registram
o pedido. Nada aqui libera nada — quem libera é você, no painel.

Por que o cadastro do site não abre sessão: o navegador não é um aparelho do
Jarvis. Gastar uma vaga de aparelho porque a pessoa se cadastrou pelo celular
seria cobrar por um acesso que ela nem usou. O aparelho é registrado quando o
Jarvis de verdade entra na conta.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .. import contas, pedidos
from ..config import config
from .conta import ip_de

rotas = APIRouter(prefix="/site", tags=["site"])


class DadosCadastro(BaseModel):
    email: str = Field(max_length=200)
    senha: str = Field(max_length=200)
    nome: str = Field(default="", max_length=80)


class DadosPedido(BaseModel):
    email: str = Field(max_length=200)
    nome: str = Field(default="", max_length=80)
    telefone: str = Field(default="", max_length=40)
    plano: str = Field(default="base", max_length=30)
    aparelhos: int = Field(default=0, ge=0, le=20)
    observacao: str = Field(default="", max_length=500)


@rotas.post("/cadastrar")
def cadastrar(dados: DadosCadastro, request: Request) -> dict:
    """Conta nova pelo site. Nasce sem assinatura, como qualquer outra."""
    usuario = contas.criar_usuario(dados.email, dados.senha, dados.nome, ip_de(request))
    pedidos.vincular_conta(usuario["id"], usuario["email"])
    return {"ok": True, "email": usuario["email"],
            "mensagem": "conta criada. Agora é só instalar o Jarvis e entrar com ela."}


@rotas.post("/pedido")
def pedir(dados: DadosPedido, request: Request) -> dict:
    resultado = pedidos.criar(
        dados.email, dados.nome, dados.telefone, dados.plano,
        dados.aparelhos, dados.observacao, ip_de(request))
    return {
        "ok": True,
        "pedido": resultado["id"],
        "repetido": resultado["repetido"],
        "mensagem": ("Pedido recebido. Assim que o pagamento for confirmado, "
                     "eu libero a sua conta e você já consegue entrar."),
        "contato": config.email_contato,
        "pix": config.chave_pix,
    }


@rotas.get("/estado")
def estado(email: str = "") -> dict:
    """O site pergunta isto para mostrar "já liberado" em vez de pedir de novo.

    Devolve o mínimo: se a conta existe e se está ativa. Nada de validade,
    aparelhos ou qualquer coisa que não precise estar num endereço público.
    """
    from .. import banco

    alvo = contas.normalizar_email(email)
    usuario = banco.um("SELECT id FROM usuarios WHERE email = ?", (alvo,))
    if usuario is None:
        return {"ok": True, "tem_conta": False, "ativa": False}
    situacao = contas.estado_da_assinatura(usuario["id"])["situacao"]
    return {"ok": True, "tem_conta": True, "ativa": situacao == "ativa"}
