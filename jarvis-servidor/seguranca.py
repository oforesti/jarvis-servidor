"""Senhas, tokens e a assinatura que o cliente confere offline.

Três mecanismos diferentes, cada um pelo motivo certo:

* **Senha** vai por argon2id — devagar de propósito, para que um banco vazado
  não vire uma lista de senhas em algumas horas de GPU.
* **Access token** é JWT HS256 de quinze minutos. Curto porque ele viaja em
  toda requisição; se vazar, expira antes de valer muito.
* **Refresh token** é aleatório puro, guardado só como SHA-256. Não precisa de
  argon2: 32 bytes de aleatoriedade não têm o que adivinhar, e ele é conferido
  a cada renovação — argon2 aqui só custaria tempo.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from cryptography.hazmat.primitives.asymmetric.ed25519 import (Ed25519PrivateKey,
                                                               Ed25519PublicKey)

from .config import config

_hasher = PasswordHasher()


# ---------------------------------------------------------------- senhas
def hash_senha(senha: str) -> str:
    return _hasher.hash(senha)


def conferir_senha(hash_guardado: str, senha: str) -> bool:
    try:
        return _hasher.verify(hash_guardado, senha)
    except (VerifyMismatchError, VerificationError, Exception):  # noqa: BLE001
        return False


def senha_fraca(senha: str) -> str:
    """Devolve o motivo, ou vazio se estiver boa.

    Regra curta de propósito: exigir símbolo e maiúscula empurra as pessoas
    para "Senha123!", que é pior do que uma frase longa. Comprimento é o que
    realmente protege.
    """
    if len(senha or "") < 8:
        return "a senha precisa ter pelo menos 8 caracteres"
    if senha.lower() in ("12345678", "senha123", "password", "jarvis123"):
        return "essa senha é fácil demais de adivinhar"
    return ""


# ---------------------------------------------------------------- tokens
def criar_acesso(usuario_id: int, aparelho_id: int, sessao_id: int,
                 admin: bool = False) -> tuple[str, int]:
    """Token curto de acesso. Devolve (token, segundos de vida)."""
    vida = config.minutos_acesso * 60
    agora = datetime.now(timezone.utc)
    corpo = {
        "sub": str(usuario_id),
        "apa": aparelho_id,
        "ses": sessao_id,
        "adm": bool(admin),
        "iat": int(agora.timestamp()),
        "exp": int((agora + timedelta(seconds=vida)).timestamp()),
    }
    return jwt.encode(corpo, config.segredo_jwt, algorithm="HS256"), vida


def ler_acesso(token: str) -> dict | None:
    try:
        return jwt.decode(token, config.segredo_jwt, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def novo_refresh() -> tuple[str, str]:
    """Devolve (token em claro, hash para guardar)."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh(token)


def hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def impressao_hash(bruta: str) -> str:
    """O identificador do aparelho nunca é guardado como veio."""
    return hashlib.sha256(f"jarvis-aparelho:{bruta}".encode("utf-8")).hexdigest()


# ------------------------------------------------- folga offline assinada
def _privada() -> Ed25519PrivateKey:
    semente = hashlib.sha256(config.chave_privada.encode("utf-8")).digest()
    return Ed25519PrivateKey.from_private_bytes(semente)


def chave_publica() -> str:
    """O que vai embutido no cliente. Pública: pode ir no APK sem problema."""
    bruta = _privada().public_key().public_bytes_raw()
    return base64.urlsafe_b64encode(bruta).decode("ascii")


def assinar_licenca(dados: dict) -> str:
    """Bloco que o cliente guarda e confere sozinho quando está sem internet.

    É por isso que a folga offline não é uma brecha: o cliente não decide até
    quando vale, ele só lê o que o servidor assinou. Esticar o prazo exigiria
    forjar uma assinatura Ed25519 — e a chave privada não sai daqui.
    """
    corpo = json.dumps(dados, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assinatura = _privada().sign(corpo)
    return (base64.urlsafe_b64encode(corpo).decode("ascii") + "."
            + base64.urlsafe_b64encode(assinatura).decode("ascii"))


def conferir_licenca(bloco: str, publica_b64: str) -> dict | None:
    """A mesma conferência que o cliente faz — aqui para os testes provarem.

    Ela vive no servidor e no cliente; manter as duas iguais é o ponto.
    """
    try:
        corpo_b64, assinatura_b64 = bloco.split(".", 1)
        corpo = base64.urlsafe_b64decode(corpo_b64)
        assinatura = base64.urlsafe_b64decode(assinatura_b64)
        publica = Ed25519PublicKey.from_public_bytes(
            base64.urlsafe_b64decode(publica_b64))
        publica.verify(assinatura, corpo)
        return json.loads(corpo)
    except Exception:  # noqa: BLE001 — qualquer falha aqui é bloco inválido
        return None
