"""Comandos de linha para a primeira configuração do servidor.

    python -m servidor.admin_cli criar-admin voce@exemplo.com
    python -m servidor.admin_cli promover voce@exemplo.com
    python -m servidor.admin_cli chave-publica

A senha nunca vem como argumento: ela é digitada e não aparece na tela nem no
histórico do terminal.
"""

from __future__ import annotations

import getpass
import sys

from . import banco, contas
from .seguranca import chave_publica, hash_senha, senha_fraca


def criar_admin(email: str) -> int:
    banco.migrar()
    if banco.um("SELECT id FROM usuarios WHERE email = ?", (contas.normalizar_email(email),)):
        print("já existe uma conta com esse e-mail — use 'promover'")
        return 1

    senha = getpass.getpass("senha do administrador: ")
    if senha != getpass.getpass("repita a senha: "):
        print("as senhas não conferem")
        return 1
    fraca = senha_fraca(senha)
    if fraca:
        print(fraca)
        return 1

    usuario = contas.criar_usuario(email, senha, nome="administrador")
    banco.executar("UPDATE usuarios SET admin = 1 WHERE id = ?", (usuario["id"],))
    print(f"administrador criado: {usuario['email']}")
    print("entre em /admin no navegador")
    return 0


def promover(email: str) -> int:
    banco.migrar()
    alvo = contas.normalizar_email(email)
    if not banco.um("SELECT id FROM usuarios WHERE email = ?", (alvo,)):
        print("não achei conta com esse e-mail")
        return 1
    banco.executar("UPDATE usuarios SET admin = 1 WHERE email = ?", (alvo,))
    print(f"{alvo} agora é administrador")
    return 0


def trocar_senha(email: str) -> int:
    banco.migrar()
    alvo = contas.normalizar_email(email)
    if not banco.um("SELECT id FROM usuarios WHERE email = ?", (alvo,)):
        print("não achei conta com esse e-mail")
        return 1
    senha = getpass.getpass("nova senha: ")
    fraca = senha_fraca(senha)
    if fraca:
        print(fraca)
        return 1
    banco.executar("UPDATE usuarios SET senha_hash = ? WHERE email = ?",
                   (hash_senha(senha), alvo))
    # trocar a senha derruba as sessões: é o que se espera de quem trocou a
    # senha justamente porque desconfia que alguém entrou
    banco.executar(
        "UPDATE sessoes SET revogada_em = ? WHERE usuario_id = "
        "(SELECT id FROM usuarios WHERE email = ?) AND revogada_em IS NULL",
        (banco.agora(), alvo))
    print("senha trocada e sessões encerradas")
    return 0


def main(argumentos: list[str]) -> int:
    if not argumentos:
        print(__doc__)
        return 1
    comando, *resto = argumentos
    if comando == "chave-publica":
        print(chave_publica())
        return 0
    if not resto:
        print("falta o e-mail")
        return 1
    if comando == "criar-admin":
        return criar_admin(resto[0])
    if comando == "promover":
        return promover(resto[0])
    if comando == "trocar-senha":
        return trocar_senha(resto[0])
    print(f"comando desconhecido: {comando}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
