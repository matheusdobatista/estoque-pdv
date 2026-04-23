"""
Dashboard gerencial.

Ajustes (patch):
- Mantém KPIs e rankings existentes.
- Adiciona: relatório detalhado por item vendido + exportação.
- Adiciona: exclusão de 1+ vendas (com estorno de estoque e limpeza de movimentos/itens).

Obs.: exclusão é uma ação forte. Recomendado usar apenas por ADMIN.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import has_role, require_login
from db import query, transaction
from utils import df_to_xlsx_bytes, money_fmt


def render() -> None:
    user = require_login()

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

    st.subheader("📦 Detalhamento (1 linha por item vendido)")
    st.caption("Exportável para Excel. Cada linha é um item de uma venda.")
    _sales_items_detail(start_ts, end_ts)

    st.divider()
    _delete_sales_tool(user, start_ts, end_ts)


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
    bar = (
        alt.Chart(df)
        .mark_bar(color="#14B8A6")
        .encode(
            x=alt.X("day:T", title="Dia"),
            y=alt.Y("revenue:Q", title="Faturamento (R$)"),
            tooltip=[
                alt.Tooltip("day:T", title="Dia"),
                alt.Tooltip("revenue:Q", title="R$", format=",.2f"),
                alt.Tooltip("sales_count:Q", title="Vendas"),
            ],
        )
        .properties(height=280)
    )
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
                hide_index=True,
                use_container_width=True,
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
                hide_index=True,
                use_container_width=True,
                column_config={"Receita": st.column_config.NumberColumn(format="R$ %.2f")},
            )
        else:
            st.caption("Sem dados.")


# ---------------------------------------------------------------------------
# Detalhamento: 1 linha por item vendido
# ---------------------------------------------------------------------------

def _sales_items_detail(start_ts: datetime, end_ts: datetime) -> None:
    rows = query(
        """
        SELECT
            s.id                              AS sale_id,
            s.created_at                      AS created_at,
            COALESCE(sl.name,'')              AS seller,
            COALESCE(s.buyer_name,'')         AS buyer,
            COALESCE(s.buyer_team,'')         AS buyer_team,
            s.payment_method                  AS payment_method,
            s.payment_status                  AS payment_status,
            p.sku                             AS sku,
            p.name                            AS product,
            si.qty                            AS qty,
            si.unit_price                     AS unit_price,
            COALESCE(si.unit_cost, p.unit_cost, 0) AS unit_cost,
            si.line_total                     AS line_total,
            CASE WHEN p.is_consigned THEN 'Consignado' ELSE 'Padrão' END AS product_type,
            COALESCE(c.name,'')               AS consignor,
            COALESCE(p.supplier_unit_cost,0)  AS consignor_unit,
            (COALESCE(p.supplier_unit_cost,0) * si.qty) AS consignor_total,
            (si.line_total - (COALESCE(si.unit_cost, p.unit_cost, 0) * si.qty)) AS gross_profit
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        LEFT JOIN sellers sl ON sl.id = s.seller_id
        JOIN products p ON p.id = si.product_id
        LEFT JOIN consignors c ON c.id = p.consignor_id
        WHERE s.created_at >= %s AND s.created_at < %s
        ORDER BY s.created_at DESC, s.id DESC
        """,
        [start_ts, end_ts],
    )

    if not rows:
        st.info("Sem itens vendidos no período.")
        return

    df = pd.DataFrame(rows)

    st.download_button(
        "⬇️ Exportar detalhamento (Excel)",
        data=df_to_xlsx_bytes(df, "ItensVendidos"),
        file_name="itens_vendidos_detalhado.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "unit_price": st.column_config.NumberColumn("Preço unit.", format="R$ %.2f"),
            "unit_cost": st.column_config.NumberColumn("Custo unit.", format="R$ %.2f"),
            "line_total": st.column_config.NumberColumn("Faturamento item", format="R$ %.2f"),
            "consignor_unit": st.column_config.NumberColumn("Repasse unit.", format="R$ %.2f"),
            "consignor_total": st.column_config.NumberColumn("Repasse total", format="R$ %.2f"),
            "gross_profit": st.column_config.NumberColumn("Lucro bruto", format="R$ %.2f"),
        },
        height=520,
    )


# ---------------------------------------------------------------------------
# Exclusão de vendas (com estorno de estoque)
# ---------------------------------------------------------------------------

def _delete_sales_tool(user, start_ts: datetime, end_ts: datetime) -> None:
    can_delete_sales = has_role(user, {"ADMIN"})

    st.subheader("🗑️ Excluir vendas")
    st.caption(
        "Atenção: excluir venda remove os itens e os movimentos associados e **estorna o estoque**. "
        "Recomendado apenas para correções (ADMIN)."
    )

    if not can_delete_sales:
        st.info("Somente ADMIN pode excluir vendas.")
        return

    sales = query(
        """
        SELECT s.id, s.created_at, COALESCE(sl.name,'') AS seller,
               COALESCE(s.buyer_name,'') AS buyer,
               COALESCE(s.buyer_team,'') AS buyer_team,
               s.payment_method, s.payment_status,
               s.total
        FROM sales s
        LEFT JOIN sellers sl ON sl.id = s.seller_id
        WHERE s.created_at >= %s AND s.created_at < %s
        ORDER BY s.created_at DESC
        LIMIT 300
        """,
        [start_ts, end_ts],
    )

    if not sales:
        st.info("Sem vendas no período.")
        return

    df = pd.DataFrame(sales)
    df.insert(0, "Excluir", False)

    editor = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Excluir": st.column_config.CheckboxColumn("Excluir"),
            "total": st.column_config.NumberColumn("Total", format="R$ %.2f"),
        },
        height=360,
    )

    picked = editor[editor["Excluir"] == True]  # noqa: E712
    picked_ids = [int(x) for x in picked["id"].tolist()] if not picked.empty else []

    if st.button(
        f"🧨 Excluir {len(picked_ids)} venda(s) selecionada(s)",
        type="primary",
        use_container_width=True,
        disabled=(len(picked_ids) == 0),
    ):
        _delete_sales_atomic(user, picked_ids)
        st.success("Vendas excluídas e estoque estornado.")
        st.rerun()


def _delete_sales_atomic(user, sale_ids: list[int]) -> None:
    """Exclui vendas e estorna estoque de forma transacional."""
    with transaction() as conn:
        for sid in sale_ids:
            # Carrega itens da venda
            cur_items = conn.execute(
                "SELECT product_id, qty FROM sale_items WHERE sale_id = %s",
                [sid],
            )
            items = cur_items.fetchall()

            # Estorna estoque
            for it in items:
                conn.execute(
                    "UPDATE products SET stock = stock + %s WHERE id = %s",
                    [int(it["qty"]), int(it["product_id"])],
                )

            # Remove movimentos criados pela venda
            conn.execute("DELETE FROM movements WHERE note = %s", [f"Venda #{sid}"])

            # Remove itens e venda
            conn.execute("DELETE FROM sale_items WHERE sale_id = %s", [sid])
            conn.execute("DELETE FROM sales WHERE id = %s", [sid])

            audit_log(user, "SALE_DELETE", "sale", sid, {"sale_id": sid}, conn=conn)
