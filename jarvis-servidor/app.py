"""O servidor de licenças do Jarvis.

    uvicorn servidor.app:app --reload        (desenvolvimento)

Ele guarda contas, assinaturas e aparelhos, e é quem decide se um Jarvis pode
funcionar. O cliente nunca decide: ele pergunta, e obedece — inclusive quando
a resposta é não.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import banco
from .config import config
from .contas import ErroConta
from .rotas.conta import rotas as rotas_conta
from .rotas.admin import rotas as rotas_admin
from .rotas.cobranca import rotas as rotas_cobranca
from .rotas.licenca import rotas as rotas_licenca
from .rotas.site import rotas as rotas_site
from .seguranca import chave_publica


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Cria as tabelas antes de atender qualquer requisição."""
    banco.migrar()
    yield


def criar_app() -> FastAPI:
    app = FastAPI(
        title="Jarvis — licenças",
        description="Contas, assinaturas e aparelhos do Jarvis.",
        version="1.0.0",
        docs_url="/documentacao",
        redoc_url=None,
        lifespan=ciclo_de_vida,
    )

    # O site mora em outro endereco (Vercel), entao o navegador so deixa ele
    # chamar este servidor se a resposta autorizar. Sem cookie: as rotas
    # publicas nao tem sessao, e `allow_credentials` com origem "*" seria
    # recusado pelo proprio navegador.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.origens_do_site,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def barrar_ip(request: Request, seguir):
        """IP que voce bloqueou na mao nao fala com o servidor.

        Fica antes de tudo, menos do painel: se voce se bloquear por engano,
        ainda consegue entrar e desfazer.
        """
        from . import acessos
        from .rotas.conta import ip_de

        if not request.url.path.startswith("/admin"):
            ip = ip_de(request)
            if ip and acessos.bloqueado(ip):
                return JSONResponse(
                    {"ok": False, "motivo": "ip_bloqueado",
                     "erro": "este acesso foi bloqueado. Fale comigo se achar que "
                             "foi engano."}, status_code=403)
        return await seguir(request)

    # Registrado DEPOIS do de IP, e por isso roda ANTES dele: no Starlette o
    # último a entrar é o primeiro a rodar. Sem configuração, nada mais
    # importa — nem consultar a lista de IPs bloqueados, que precisa do banco.
    @app.middleware("http")
    async def conferir_configuracao(request: Request, seguir):
        """Servidor mal configurado recusa tudo — dizendo o que falta.

        Atender com um segredo vazio seria pior do que recusar: qualquer um
        forjaria um token. E recusar calado foi o que já aconteceu uma vez,
        com um "FUNCTION_INVOCATION_FAILED" que não ajudou ninguém a entender
        que faltava uma variável de ambiente.
        """
        faltando = config.incompleto()
        if faltando:
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "motivo": "configuracao_incompleta",
                    "erro": "este servidor ainda não está configurado",
                    "falta": faltando,
                    "como_resolver": (
                        "No Vercel: Settings > Environment Variables, adicione as "
                        "que estão em 'falta', e depois publique de novo "
                        "(npx vercel --prod). Sem publicar de novo, o que você "
                        "adicionar não vale."
                    ),
                },
            )
        return await seguir(request)

    @app.exception_handler(ErroConta)
    def erro_de_conta(request: Request, erro: ErroConta) -> JSONResponse:
        """Toda recusa sai no mesmo formato, com texto que dá para mostrar na tela."""
        corpo = {"ok": False, "erro": erro.mensagem, "motivo": erro.motivo}
        corpo.update(erro.extra)
        return JSONResponse(status_code=erro.http, content=corpo)

    @app.get("/saude", tags=["servico"])
    def saude() -> dict:
        """O que o PaaS chama para saber se o serviço está de pé."""
        return {"ok": True}

    @app.get("/chave-publica", tags=["servico"])
    def publica() -> dict:
        """A chave que os clientes usam para conferir o bloco de folga offline.

        Pública de verdade: serve só para conferir assinatura, nunca para criar
        uma. Fica exposta para o cliente poder buscá-la na primeira instalação
        em vez de eu ter que reembutir o app a cada troca de chave.
        """
        return {"chave": chave_publica()}

    app.include_router(rotas_conta)
    app.include_router(rotas_licenca)
    app.include_router(rotas_cobranca)
    app.include_router(rotas_site)
    app.include_router(rotas_admin)
    return app


app = criar_app()
