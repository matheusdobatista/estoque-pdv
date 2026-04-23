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
    "Externa",
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
    """Serializa DataFrame como XLSX em memória. Use st.download_button.

    Observação: pandas/openpyxl não aceitam datetimes com timezone.
    (Ex.: TIMESTAMPTZ do Postgres vira datetime64[ns, UTC] no pandas)
    """
    safe = df.copy()
    for col in safe.columns:
        s = safe[col]
        # datetime64 com tz
        try:
            if hasattr(s.dtype, "tz") and s.dtype.tz is not None:
                safe[col] = pd.to_datetime(s).dt.tz_convert(None)
                continue
        except Exception:
            pass

        # object com Timestamp timezone-aware
        if str(s.dtype) == "object":
            def _fix(v):
                try:
                    if isinstance(v, pd.Timestamp) and v.tz is not None:
                        return v.tz_convert(None).to_pydatetime()
                except Exception:
                    return v
                return v
            safe[col] = s.map(_fix)

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        safe.to_excel(writer, index=False, sheet_name=(sheet_name[:31] or "Dados"))
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
    if ts is None:
        return "—"
    return ts.strftime("%d/%m/%Y %H:%M")
