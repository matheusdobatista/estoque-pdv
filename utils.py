"""Constantes e utilitários genéricos."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

import pandas as pd


BUYER_TEAMS = [
    "Animação",
    "Canto",
    "Círculos",
    "Coordenação Geral",
    "Despertar",
    "Encontrista - Círculo Amarelo",
    "Encontrista - Círculo Azul",
    "Encontrista - Círculo Verde",
    "Encontrista - Círculo Vermelho",
    "Externo",
    "Lanche",
    "Mercadinho",
    "Ordem",
    "Refeição",
    "Sala",
    "Secretaria",
    "Taxistas",
    "Vigília",
]

PAYMENT_METHODS = ["Dinheiro", "PIX", "Crédito", "Débito", "Fiado"]

ROLE_LABELS = {
    "ADMIN": "Administrador",
    "OPERADOR": "Operador (PDV)",
    "GERENCIAL": "Gerencial (Consulta)",
}


def money_fmt(v: Any) -> str:
    """Formata um número como moeda BRL."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "R$ 0,00"
    try:
        dec = Decimal(str(v))
    except Exception:
        return "R$ 0,00"
    # Formato brasileiro: 1.234,56
    s = f"{dec:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def df_to_xlsx_bytes(df: pd.DataFrame, sheet_name: str = "Dados") -> bytes:
    """Serializa DataFrame como XLSX em memória. Use st.download_button."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31] or "Dados")
    return buf.getvalue()


def next_sku_default(prefix: str = "DSP", width: int = 4) -> str:
    """
    Gera próximo SKU sequencial consultando o banco.
    Formato: PREFIXO-0001
    """
    from db import query_one

    row = query_one(
        "SELECT MAX(CAST(NULLIF(regexp_replace(sku, '^[^0-9]*', ''), '') AS INTEGER)) AS max_n "
        "FROM products WHERE sku LIKE %s",
        [f"{prefix}%"],
    )
    n = (row["max_n"] if row and row["max_n"] else 0) + 1
    return f"{prefix}-{str(n).zfill(width)}"


def fmt_ts(ts: datetime | None) -> str:
    """Formata timestamps com segurança (inclui NaT do pandas)."""
    # pandas pode trazer NaT (Not-a-Time) em colunas datetime
    if ts is None or pd.isna(ts):
        return "—"
    try:
        return ts.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return "—"
