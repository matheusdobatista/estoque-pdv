"""
Log de auditoria. Chamadas explícitas nas operações importantes:
venda, quitação de fiado, criar/editar/excluir produto, usuário, etc.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from auth import CurrentUser
from db import get_conn


def log(
    user: CurrentUser | None,
    action: str,
    entity: str | None = None,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
    *,
    conn: psycopg.Connection | None = None,
) -> None:
    """
    Registra uma linha em audit_log.

    Pode receber `conn` para participar de uma transação em andamento
    (caso contrário abre própria conexão).
    """
    sql = (
        "INSERT INTO audit_log (user_id, username, action, entity, entity_id, details) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb)"
    )
    params = [
        user.id if user else None,
        user.username if user else None,
        action,
        entity,
        entity_id,
        json.dumps(details or {}, ensure_ascii=False, default=str),
    ]

    if conn is not None:
        conn.execute(sql, params)
        return

    with get_conn() as c:
        c.execute(sql, params)
        c.commit()
