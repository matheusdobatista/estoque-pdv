"""
Migração única: SQLite (estoque_pdv.db) → PostgreSQL.

Uso:
    # 1) Setar URL do Postgres
    export DATABASE_URL='postgresql://user:pass@host/db?sslmode=require'

    # 2) Rodar schema (se ainda não rodou)
    psql "$DATABASE_URL" -f schema.sql
    psql "$DATABASE_URL" -f seed.sql

    # 3) Apontar pro sqlite de origem e executar
    python scripts/migrate_from_sqlite.py /caminho/para/estoque_pdv.db

Características:
- Idempotente pra users (ON CONFLICT DO NOTHING no seed).
- Preserva IDs originais (usa INSERT com id explícito e depois ajusta sequences).
- Tabelas migradas: consignors, sellers, products, movements, sales, sale_items.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import psycopg
from psycopg.rows import dict_row


TABLES_IN_ORDER = [
    # (table, columns_sqlite, columns_pg)
    ("consignors", ["id", "name", "phone", "address", "pix_key", "active", "created_at"],
                   ["id", "name", "phone", "address", "pix_key", "active", "created_at"]),
    ("sellers",    ["id", "name", "active", "created_at"],
                   ["id", "name", "active", "created_at"]),
    ("products",   ["id", "name", "sku", "price", "unit_cost", "supplier_unit_cost",
                    "stock", "min_stock", "active", "is_consigned", "consignor_id", "created_at"],
                   ["id", "name", "sku", "price", "unit_cost", "supplier_unit_cost",
                    "stock", "min_stock", "active", "is_consigned", "consignor_id", "created_at"]),
    ("movements",  ["id", "created_at", "type", "product_id", "qty", "note"],
                   ["id", "created_at", "type", "product_id", "qty", "note"]),
    ("sales",      ["id", "created_at", "seller_id", "buyer_name", "buyer_team",
                    "payment_method", "payment_status", "total", "paid", "change"],
                   ["id", "created_at", "seller_id", "buyer_name", "buyer_team",
                    "payment_method", "payment_status", "total", "paid", "change_amount"]),
    ("sale_items", ["id", "sale_id", "product_id", "qty", "unit_price", "unit_cost", "line_total"],
                   ["id", "sale_id", "product_id", "qty", "unit_price", "unit_cost", "line_total"]),
]


def _coerce_bool(v):
    """SQLite guarda INTEGER 0/1 em colunas 'active'/'is_consigned'."""
    if v is None:
        return None
    return bool(int(v))


def migrate(sqlite_path: str, pg_url: str) -> None:
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite não encontrado: {sqlite_path}")

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row

    dst = psycopg.connect(pg_url, row_factory=dict_row)

    try:
        with dst.transaction():
            for table, sqlite_cols, pg_cols in TABLES_IN_ORDER:
                rows = list(src.execute(f"SELECT {', '.join(sqlite_cols)} FROM {table}"))
                if not rows:
                    print(f"[{table}] 0 linhas (vazio)")
                    continue

                values = []
                for row in rows:
                    tup = []
                    for col in sqlite_cols:
                        v = row[col]
                        if col in ("active", "is_consigned"):
                            v = _coerce_bool(v)
                        tup.append(v)
                    values.append(tuple(tup))

                placeholders = ", ".join(["%s"] * len(pg_cols))
                sql = (
                    f"INSERT INTO {table} ({', '.join(pg_cols)}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT (id) DO NOTHING"
                )
                with dst.cursor() as cur:
                    cur.executemany(sql, values)
                print(f"[{table}] {len(values)} linha(s) inseridas")

            # Reajusta as sequences pro máximo id existente em cada tabela
            seqs = {
                "consignors": "consignors_id_seq",
                "sellers": "sellers_id_seq",
                "products": "products_id_seq",
                "movements": "movements_id_seq",
                "sales": "sales_id_seq",
                "sale_items": "sale_items_id_seq",
            }
            with dst.cursor() as cur:
                for table, seq in seqs.items():
                    cur.execute(
                        f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {table}), 1))",
                        [seq],
                    )
            print("Sequences ajustadas.")

        print("\n✅ Migração concluída com sucesso.")
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/migrate_from_sqlite.py <caminho_sqlite>")
        sys.exit(1)

    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url:
        print("Erro: defina a variável de ambiente DATABASE_URL.")
        sys.exit(2)

    migrate(sys.argv[1], pg_url)
