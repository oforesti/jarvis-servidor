"""Configuração do servidor de licenças.

Tudo vem do ambiente — nenhum segredo no código, porque este repositório vai
junto com o cliente e o `jarvis/` inteiro é copiado para dentro do APK.

Em desenvolvimento, os segredos que faltam são gerados uma vez e guardados em
`dados/segredos.json`, fora do controle de versão. Em produção eles vêm das
variáveis de ambiente do serviço, e o arquivo nem chega a existir.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DADOS = Path(os.getenv("JARVIS_LICENCA_DADOS") or (RAIZ / "dados"))
SEGREDOS = DADOS / "segredos.json"


def _guardados() -> dict:
    if not SEGREDOS.exists():
        return {}
    try:
        return json.loads(SEGREDOS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _gravar(dados: dict) -> None:
    DADOS.mkdir(parents=True, exist_ok=True)
    SEGREDOS.write_text(json.dumps(dados, indent=2), encoding="utf-8")
    try:                      # no Linux, só o dono lê
        SEGREDOS.chmod(0o600)
    except OSError:
        pass


# Variáveis obrigatórias que não vieram. Enquanto tiver alguma coisa aqui, o
# servidor não atende ninguém: um segredo vazio assinaria token que qualquer
# um forjaria.
FALTANDO: list[str] = []


def sem_disco() -> bool:
    """Estamos num lugar onde o que se grava some depois da resposta?

    No Vercel cada requisição pode cair numa máquina nova. Guardar segredo em
    arquivo ali é o mesmo que inventar um novo a cada boot.
    """
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def segredo(nome: str, tamanho: int = 48) -> str:
    """Lê do ambiente; na falta, inventa um e guarda para o próximo boot.

    Gerar a cada boot seria pior do que parece: todo reinício derrubaria a
    sessão de todo mundo, porque o segredo do JWT teria mudado. E em serverless
    não existe "próximo boot" com o mesmo disco — por isso lá a falta da
    variável é erro, e um erro barulhento, em vez de um sistema que esquece
    todo mundo a cada quinze minutos sem ninguém entender por quê.
    """
    do_ambiente = (os.getenv(nome) or "").strip()
    if do_ambiente:
        return do_ambiente
    if sem_disco():
        # Anotar em vez de explodir. Explodir no import derruba a função
        # inteira, e quem publicou recebe um "FUNCTION_INVOCATION_FAILED"
        # que não diz nada. Assim o servidor sobe, recusa todas as
        # requisições, e a recusa diz o nome da variável que falta.
        if nome not in FALTANDO:
            FALTANDO.append(nome)
        return ""
    guardados = _guardados()
    if not guardados.get(nome):
        guardados[nome] = secrets.token_urlsafe(tamanho)
        _gravar(guardados)
    return guardados[nome]


def _int(nome: str, padrao: int) -> int:
    try:
        return int((os.getenv(nome) or "").strip() or padrao)
    except ValueError:
        return padrao


class Config:
    def __init__(self):
        self.banco = Path(os.getenv("JARVIS_LICENCA_BANCO") or (DADOS / "licencas.db"))

        # assinatura do access token (HS256) — só o servidor precisa conhecer
        self.segredo_jwt = segredo("JARVIS_LICENCA_SEGREDO")

        # chave Ed25519 que assina o bloco de folga offline. A privada fica
        # aqui; os clientes carregam apenas a pública.
        self.chave_privada = segredo("JARVIS_LICENCA_CHAVE_ED25519", 32)

        self.minutos_acesso = _int("JARVIS_LICENCA_MINUTOS_ACESSO", 15)
        self.dias_refresh = _int("JARVIS_LICENCA_DIAS_REFRESH", 30)
        self.dias_folga = _int("JARVIS_LICENCA_DIAS_FOLGA", 7)

        # quantos aparelhos o plano base libera, antes dos adicionais pagos
        self.aparelhos_inclusos = _int("JARVIS_LICENCA_APARELHOS_INCLUSOS", 1)

        # conta nova nasce sem acesso; com isto > 0, ganha um período de teste
        self.dias_de_teste = _int("JARVIS_LICENCA_DIAS_TESTE", 0)

        # trava simples de força bruta no login
        self.tentativas_max = _int("JARVIS_LICENCA_TENTATIVAS", 10)
        self.tentativas_janela_min = _int("JARVIS_LICENCA_TENTATIVAS_JANELA", 15)

        # para onde a tela de conta manda quem quer assinar ou mudar de plano
        self.url_assinatura = (os.getenv("JARVIS_LICENCA_URL_ASSINATURA") or "").strip()

        # segredo que o gateway usa para assinar o webhook (quando houver)
        self.segredo_webhook = segredo("JARVIS_LICENCA_SEGREDO_WEBHOOK")

        # o site que pode falar com este servidor. Separe por virgula; "*"
        # libera qualquer origem, o que so e aceitavel porque as rotas /site
        # nao usam cookie nem devolvem dado de ninguem.
        self.origens_do_site = [
            o.strip() for o in (os.getenv("JARVIS_LICENCA_SITE") or "*").split(",")
            if o.strip()
        ]
        # o que a tela de "pedido recebido" mostra para a pessoa pagar
        self.email_contato = (os.getenv("JARVIS_LICENCA_CONTATO") or "").strip()
        self.chave_pix = (os.getenv("JARVIS_LICENCA_PIX") or "").strip()

        # conferido aqui e não no banco.py para não criar import circular
        self.banco_remoto = any(
            (os.getenv(n) or "").strip()
            for n in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL",
                      "JARVIS_LICENCA_POSTGRES"))

    def sem_disco(self) -> bool:
        return sem_disco()

    def incompleto(self) -> list[str]:
        """O que falta para este servidor poder atender."""
        faltando = list(FALTANDO)
        if sem_disco() and not self.banco_remoto:
            faltando.append("DATABASE_URL (ligue o banco em Storage > Connect Project)")
        return faltando


config = Config()
