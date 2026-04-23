"""
Dashboard gerencial.
Versão inicial: KPIs principais + gráficos de evolução e rankings.
(Será expandido no próximo turno com mais detalhes.)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from auth import require_login
from db import query
from utils import df_to_xlsx_bytes, money_fmt


def render() -> None:
    require_login()

    st.title("📊 Dashboard")

    today = date.today()
    c1, c2, _ = st.columns([1, 1, 3])
    start = c1.date_input("De", value=today - timedelta(days=30))
    end = c2.date_input("Até", value=today)

    start_ts = datetime.combine(start, datetime.min.time())
    end_ts = datetime.combine(end + timedelta(days=1), datetime.min.time())

    _kpis(start_ts, end_ts)
    st.divider()
    _charts(start_ts, end_ts)
    st.divider()
    _rankings(start_ts, end_ts)
    st.divider()
    _low_stock()


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

def _kpis(start_ts: datetime, end_ts: datetime) -> None:
    r = query(
        """
        SELECT
            COUNT(*)                                      AS sales_count,
            COALESCE(SUM(total), 0)                       AS revenue,
            COALESCE(AVG(total), 0)                       AS ticket_avg,
            COALESCE(SUM(CASE WHEN payment_status='ABERTO' THEN total END), 0) AS open_total,
            COUNT(*) FILTER (WHERE payment_status='ABERTO') AS open_count
        FROM sales
        WHERE created_at >= %s AND created_at < %s
        """,
        [start_ts, end_ts],
    )[0]

    # Lucro bruto = sum(qty * (unit_price - unit_cost)) nas sale_items
    profit_row = query(
        """
        SELECT COALESCE(SUM(si.qty * (si.unit_price - COALESCE(si.unit_cost, 0))), 0) AS gross_profit,
               COALESCE(SUM(si.line_total), 0) AS gross_revenue
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE s.created_at >= %s AND s.created_at < %s
          AND s.payment_status = 'PAGO'
        """,
        [start_ts, end_ts],
    )[0]

    gross_profit = float(profit_row["gross_profit"] or 0)
    gross_rev = float(profit_row["gross_revenue"] or 0)
    margin = (gross_profit / gross_rev * 100) if gross_rev > 0 else 0.0

    k1, k2, k3 = st.columns(3)
    k1.metric("Faturamento", money_fmt(r["revenue"]))
    k2.metric("Vendas", f"{r['sales_count']}")
    k3.metric("Ticket médio", money_fmt(r["ticket_avg"]))

    k4, k5, k6 = st.columns(3)
    k4.metric("Lucro bruto (pagos)", money_fmt(gross_profit))
    k5.metric("Margem", f"{margin:.1f}%")
    k6.metric("Em aberto (fiado)", money_fmt(r["open_total"]), delta=f"{r['open_count']} vendas")


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _charts(start_ts: datetime, end_ts: datetime) -> None:
    rows = query(
        """
        SELECT DATE(created_at) AS day,
               COUNT(*)          AS sales_count,
               SUM(total)        AS revenue
        FROM sales
        WHERE created_at >= %s AND created_at < %s
        GROUP BY DATE(created_at)
        ORDER BY day
        """,
        [start_ts, end_ts],
    )
    if not rows:
        st.info("Sem vendas no período.")
        return

    df = pd.DataFrame(rows)
    df["revenue"] = df["revenue"].astype(float)

    st.subheader("Faturamento por dia")
    bar = alt.Chart(df).mark_bar(color="#14B8A6").encode(
        x=alt.X("day:T", title="Dia"),
        y=alt.Y("revenue:Q", title="Faturamento (R$)"),
        tooltip=[
            alt.Tooltip("day:T", title="Dia"),
            alt.Tooltip("revenue:Q", title="R$", format=",.2f"),
            alt.Tooltip("sales_count:Q", title="Vendas"),
        ],
    ).properties(height=280)
    st.altair_chart(bar, use_container_width=True)


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------

def _rankings(start_ts: datetime, end_ts: datetime) -> None:
    left, right = st.columns(2)

    with left:
        st.subheader("Top 10 produtos")
        rows = query(
            """
            SELECT p.name,
                   SUM(si.qty)        AS qty,
                   SUM(si.line_total) AS revenue
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            JOIN products p ON p.id = si.product_id
            WHERE s.created_at >= %s AND s.created_at < %s
            GROUP BY p.name
            ORDER BY revenue DESC
            LIMIT 10
            """,
            [start_ts, end_ts],
        )
        if rows:
            df = pd.DataFrame(rows)
            df["revenue"] = df["revenue"].astype(float)
            st.dataframe(
                df.rename(columns={"name": "Produto", "qty": "Qtd", "revenue": "Receita"}),
                hide_index=True, use_container_width=True,
                column_config={"Receita": st.column_config.NumberColumn(format="R$ %.2f")},
            )
        else:
            st.caption("Sem dados.")

    with right:
        st.subheader("Top vendedores")
        rows = query(
            """
            SELECT COALESCE(sl.name, '(sem vendedor)') AS seller,
                   COUNT(*)      AS sales,
                   SUM(s.total)  AS revenue
            FROM sales s
            LEFT JOIN sellers sl ON sl.id = s.seller_id
            WHERE s.created_at >= %s AND s.created_at < %s
            GROUP BY sl.name
            ORDER BY revenue DESC
            LIMIT 10
            """,
            [start_ts, end_ts],
        )
        if rows:
            df = pd.DataFrame(rows)
            df["revenue"] = df["revenue"].astype(float)
            st.dataframe(
                df.rename(columns={"seller": "Vendedor", "sales": "Vendas", "revenue": "Receita"}),
                hide_index=True, use_container_width=True,
                column_config={"Receita": st.column_config.NumberColumn(format="R$ %.2f")},
            )
        else:
            st.caption("Sem dados.")


# ---------------------------------------------------------------------------
# Low stock
# ---------------------------------------------------------------------------

def _low_stock() -> None:
    rows = query("""
        SELECT sku, name, stock, min_stock
        FROM products
        WHERE active = TRUE AND stock <= min_stock
        ORDER BY (stock - min_stock), name
    """)
    st.subheader("⚠️ Estoque baixo")
    if not rows:
        st.caption("Tudo no azul.")
        return
    df = pd.DataFrame(rows).rename(columns={
        "sku": "SKU", "name": "Produto", "stock": "Estoque", "min_stock": "Mínimo",
    })
    st.dataframe(df, hide_index=True, use_container_width=True)
