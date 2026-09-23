"""Porta de entrada do servidor no Vercel.

O Vercel publica esta pasta (`servidor/`) como raiz do projeto e procura as
funções em `api/`. Só que os módulos daqui se importam entre si como pacote
(`from . import banco`), e um arquivo solto no `api/` não tem pacote nenhum
por perto.

A saída é registrar a pasta de cima como o pacote `servidor` antes de importar
qualquer coisa. Três linhas, um arquivo, e o resto do código continua igual ao
que roda na sua máquina — que é o ponto: o mesmo código nos dois lugares,
testado uma vez só.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

if "servidor" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "servidor", RAIZ / "__init__.py", submodule_search_locations=[str(RAIZ)])
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["servidor"] = modulo
    spec.loader.exec_module(modulo)

from servidor.app import app  # noqa: E402

# o Vercel procura por um ASGI chamado `app`
__all__ = ["app"]
