"""
Camada de acesso ao banco PostgreSQL.

Design:
- Um único ConnectionPool por processo Streamlit (cached via st.cache_resource).
- Helpers simples: query() retorna list[dict], execute() para INSERT/UPDATE/DELETE.
- Context manager transaction() para operações multi-statement com rollback automático.
- Todos os parâmetros são passados separadamente (nunca f-string em SQL) -> imune a SQL injection.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import psycopg
import streamlit as st
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_pool() -> ConnectionPool:
    """
    Cria/retorna o ConnectionPool global.

    Streamlit roda o script do topo a cada interação; @st.cache_resource
    garante que o pool só seja criado uma vez por processo worker.
    """
    try:
        url = st.secrets["postgres"]["url"]
    except (KeyError, FileNotFoundError) as e:
        st.error(
            "❌ Configuração do banco não encontrada. "
            "Adicione `postgres.url` em .streamlit/secrets.toml "
            "(ou em App Settings → Secrets no Streamlit Cloud)."
        )
        st.stop()

    pool = ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=10,
        timeout=30,
        # kwargs passados a psycopg.connect
        kwargs={"row_factory": dict_row, "autocommit": False},
        open=False,
    )
    pool.open(wait=True, timeout=15)
    return pool


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------

@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """
    Pega uma conexão do pool. Commit/rollback manual.
    Use para queries simples de leitura/escrita.
    """
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """
    Transação atômica. Commit no sucesso, rollback em qualquer exceção.

    Uso típico (venda no PDV):

        with transaction() as conn:
            cur = conn.execute("SELECT stock FROM products WHERE id = %s FOR UPDATE", [pid])
            ...
            conn.execute("INSERT INTO sales ...")
            conn.execute("UPDATE products SET stock = stock - %s WHERE id = %s", [qty, pid])
    """
    pool = get_pool()
    with pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def query(sql: str, params: Sequence[Any] | None = None) -> list[dict]:
    """Executa SELECT e retorna list[dict]. Nunca usar f-string dentro do sql."""
    with get_conn() as conn:
        cur = conn.execute(sql, params or [])
        return list(cur.fetchall())


def query_one(sql: str, params: Sequence[Any] | None = None) -> dict | None:
    """SELECT que retorna no máximo 1 linha."""
    with get_conn() as conn:
        cur = conn.execute(sql, params or [])
        row = cur.fetchone()
        return dict(row) if row else None


def execute(sql: str, params: Sequence[Any] | None = None) -> int:
    """
    INSERT/UPDATE/DELETE sem retorno. Commita imediatamente.
    Retorna rowcount.
    """
    with get_conn() as conn:
        cur = conn.execute(sql, params or [])
        conn.commit()
        return cur.rowcount


def execute_returning(sql: str, params: Sequence[Any] | None = None) -> dict | None:
    """INSERT/UPDATE ... RETURNING. Commita. Útil p/ pegar id recém-criado."""
    with get_conn() as conn:
        cur = conn.execute(sql, params or [])
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Schema bootstrap (roda uma vez no boot)
# ---------------------------------------------------------------------------

def ensure_schema() -> None:
    """
    Garante que o schema existe. Lê schema.sql do disco.
    Chamado uma única vez no boot (cached).
    """
    import os
    root = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(root, "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        ddl = f.read()
    with get_conn() as conn:
        conn.execute(ddl)
        conn.commit()


@st.cache_resource(show_spinner=False)
def bootstrap() -> bool:
    """Roda ensure_schema() uma única vez por processo."""
    ensure_schema()
    return True
