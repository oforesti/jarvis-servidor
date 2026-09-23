"""Acesso ao banco — o único arquivo que sabe qual banco está por baixo.

Ele fala com **dois**, e isso não é indecisão:

* **Postgres**, quando existe uma variável de conexão no ambiente. É o de
  produção: no Vercel o disco some entre uma requisição e outra, então um
  arquivo SQLite lá seria apagado o tempo todo — você cadastraria alguém e
  minutos depois a conta não existiria mais.
* **SQLite**, quando não existe. É o de desenvolvimento e o dos testes: roda
  sem instalar servidor nenhum, e é o que deixa a suíte inteira rodar na sua
  máquina em trinta segundos.

O resto do sistema não sabe de nada disso. As consultas do código usam `?` e
recebem linhas que se leem como dicionário, nos dois casos. As diferenças de
dialeto — placeholder, id gerado, várias instruções de uma vez — morrem aqui
dentro.

O que esse arranjo cobra: um teste que passa no SQLite não prova o Postgres.
Por isso existe o `fumaca.py`, que roda contra o servidor de verdade depois do
deploy.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import config

PASTA = Path(__file__).resolve().parent
ESQUEMA_SQLITE = PASTA / "esquema.sql"
ESQUEMA_POSTGRES = PASTA / "esquema_pg.sql"

# Tabelas cujo INSERT devolve um id. As de fora (assinaturas, ips_bloqueados)
# têm outra chave primária, e pedir `RETURNING id` nelas seria erro.
COM_ID = {"usuarios", "aparelhos", "sessoes", "recusas", "eventos_cobranca",
          "pedidos", "acessos"}


def endereco_postgres() -> str:
    """As variáveis que Vercel, Neon e Railway usam, em ordem de preferência."""
    for nome in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL",
                 "JARVIS_LICENCA_POSTGRES"):
        valor = (os.getenv(nome) or "").strip()
        if valor:
            return valor
    return ""


def no_postgres() -> bool:
    return bool(endereco_postgres())


def agora() -> str:
    """Horário sempre em UTC e sempre no mesmo formato.

    O servidor pode acordar em qualquer fuso (e um serviço em nuvem troca de
    máquina sem avisar); comparar datas guardadas em fusos diferentes seria
    uma fonte de bug silencioso em cima de validade de assinatura.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def para_data(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        d = datetime.fromisoformat(str(texto))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# =====================================================================
# tradução de dialeto
# =====================================================================
def _traduzir(sql: str) -> str:
    """`?` vira `%s` no Postgres. O `%` literal precisa dobrar antes disso.

    A ordem importa: trocar `?` primeiro criaria `%s`, e a dobra de `%` em
    seguida estragaria justamente o que acabou de ser criado.
    """
    return sql.replace("%", "%%").replace("?", "%s")


def _tabela_do_insert(sql: str) -> str:
    partes = sql.strip().split()
    if len(partes) >= 3 and partes[0].upper() == "INSERT" and partes[1].upper() == "INTO":
        return partes[2].strip("(").lower()
    return ""


# =====================================================================
# conexão
# =====================================================================
@contextmanager
def conexao():
    if no_postgres():
        import psycopg
        from psycopg.rows import dict_row

        cx = psycopg.connect(endereco_postgres(), row_factory=dict_row,
                             connect_timeout=10)
        try:
            yield cx
            cx.commit()
        except Exception:
            cx.rollback()
            raise
        finally:
            cx.close()
        return

    config.banco.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(config.banco, timeout=10)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    # WAL: leitura não trava escrita. Sem isto, duas requisições simultâneas
    # já bastam para "database is locked" no primeiro dia de uso real.
    cx.execute("PRAGMA journal_mode = WAL")
    try:
        yield cx
        cx.commit()
    except Exception:
        cx.rollback()
        raise
    finally:
        cx.close()


def _instrucoes(texto: str) -> list[str]:
    """Corta o arquivo de esquema em instruções executáveis.

    Cortar só por `;` não basta: sobra um último pedaço com os comentários do
    fim do arquivo, e o Postgres recusa isso com "syntax error at end of
    input" — um erro que não diz em nada o que aconteceu de verdade.
    """
    limpo = []
    for linha in texto.splitlines():
        # o comentário sai ANTES do corte: um deles tem `;` no meio do texto,
        # e cortar primeiro partia a instrução ao meio
        sem_comentario = linha.split("--", 1)[0].rstrip()
        if sem_comentario.strip():
            limpo.append(sem_comentario)

    return [instrucao for instrucao in "\n".join(limpo).split(";") if instrucao.strip()]


def migrar() -> None:
    """Cria as tabelas. Idempotente: roda a cada boot sem fazer estrago."""
    arquivo = ESQUEMA_POSTGRES if no_postgres() else ESQUEMA_SQLITE
    texto = arquivo.read_text(encoding="utf-8")
    with conexao() as cx:
        if no_postgres():
            # o psycopg usa o protocolo estendido, que recusa várias
            # instruções numa chamada só
            for instrucao in _instrucoes(texto):
                cx.execute(instrucao)
        else:
            cx.executescript(texto)


def consultar(sql: str, params: tuple = ()) -> list:
    with conexao() as cx:
        if no_postgres():
            with cx.cursor() as cursor:
                cursor.execute(_traduzir(sql), params)
                return cursor.fetchall()
        return cx.execute(sql, params).fetchall()


def um(sql: str, params: tuple = ()):
    with conexao() as cx:
        if no_postgres():
            with cx.cursor() as cursor:
                cursor.execute(_traduzir(sql), params)
                return cursor.fetchone()
        return cx.execute(sql, params).fetchone()


def executar(sql: str, params: tuple = ()) -> int:
    """Devolve o id inserido (ou a quantidade de linhas afetadas)."""
    if not no_postgres():
        with conexao() as cx:
            cursor = cx.execute(sql, params)
            return cursor.lastrowid or cursor.rowcount

    tabela = _tabela_do_insert(sql)
    devolve_id = tabela in COM_ID and "RETURNING" not in sql.upper()
    texto = _traduzir(sql) + (" RETURNING id" if devolve_id else "")
    with conexao() as cx:
        with cx.cursor() as cursor:
            cursor.execute(texto, params)
            if devolve_id:
                linha = cursor.fetchone()
                return int(linha["id"]) if linha else 0
            return cursor.rowcount


def anotar_recusa(motivo: str, email: str = "", impressao: str = "",
                  detalhe: str = "", ip: str = "") -> None:
    """Registro de abuso. Nunca levanta exceção: auditoria não pode derrubar
    a resposta que ela está auditando."""
    try:
        executar(
            "INSERT INTO recusas (quando, email, impressao, motivo, detalhe, ip) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (agora(), (email or "").lower()[:200], (impressao or "")[:80],
             motivo[:60], (detalhe or "")[:300], (ip or "")[:60]),
        )
    except Exception:  # noqa: BLE001
        pass
