"""Dashboard gerencial (sem filtro de data).

Requisitos do Matheus:
- Remover gráfico de faturamento por dia.
- Manter KPIs em cards.
- Manter rankings (produtos e vendedores).
- Manter relatório de prestação de contas por consignante.
- Manter relatório detalhado (1 linha por item vendido) + export Excel.
- Remover bloco de estoque baixo.

Observação: export Excel usa utils.df_to_xlsx_bytes, que sanitiza TZ.
"""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from auth import require_login
from db import query
from utils import df_to_xlsx_bytes, money_fmt


def render() -> None:
    require_login()

    st.title("📊 Dashboard")

    _kpis()
    st.divider()
    _rankings()
    st.divider()
    _consignor_settlement()
    st.divider()
    _sales_items_detail()


# ---------------------------------------------------------------------------
# KPIs (sem período)
# ---------------------------------------------------------------------------

def _kpis() -> None:
    r = query(
        """
        SELECT
            COUNT(*)                                      AS sales_count,
            COALESCE(SUM(total), 0)                       AS revenue,
            COALESCE(AVG(total), 0)                       AS ticket_avg,
            COALESCE(SUM(CASE WHEN payment_status='ABERTO' THEN total END), 0) AS open_total,
            COUNT(*) FILTER (WHERE payment_status='ABERTO') AS open_count
        FROM sales
        """
    )[0]

    profit_row = query(
        """
        SELECT
            COALESCE(SUM(si.qty * (si.unit_price - COALESCE(si.unit_cost, 0))), 0) AS gross_profit,
            COALESCE(SUM(si.line_total), 0) AS gross_revenue
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE s.payment_status = 'PAGO'
        """
    )[0]

    gross_profit = float(profit_row["gross_profit"] or 0)
    gross_rev = float(profit_row["gross_revenue"] or 0)
    margin = (gross_profit / gross_rev * 100) if gross_rev > 0 else 0.0

    a, b, c, d = st.columns(4)
    a.metric("Faturamento", money_fmt(r["revenue"]))
    b.metric("Vendas", f"{r['sales_count']}")
    c.metric("Ticket médio", money_fmt(r["ticket_avg"]))
    d.metric("Em aberto (fiado)", money_fmt(r["open_total"]), delta=f"{r['open_count']} vendas")

    e, f = st.columns(2)
    e.metric("Lucro bruto (pagos)", money_fmt(gross_profit))
    f.metric("Margem (pagos)", f"{margin:.1f}%")


# ---------------------------------------------------------------------------
# Rankings (barras horizontais)
# ---------------------------------------------------------------------------

def _rankings() -> None:
    st.subheader("🏅 Rankings")
    st.caption("Top produtos e vendedores (sem filtro de data).")

    left, right = st.columns(2)

    with left:
        rows = query(
            """
            SELECT
              p.name AS produto,
              COALESCE(SUM(si.qty),0) AS qtd
            FROM sale_items si
            JOIN products p ON p.id = si.product_id
            GROUP BY p.name
            ORDER BY qtd DESC
            LIMIT 10
            """
        )
        if rows:
            df = pd.DataFrame(rows)
            ch = (
                alt.Chart(df)
                .mark_bar()
                .encode(
                    x=alt.X("qtd:Q", title="Qtd"),
                    y=alt.Y("produto:N", sort="-x", title=""),
                    tooltip=["produto:N", "qtd:Q"],
                )
                .properties(height=280)
            )
            st.markdown("**Top 10 produtos (quantidade)**")
            st.altair_chart(ch, use_container_width=True)
        else:
            st.info("Sem itens vendidos ainda.")

    with right:
        rows = query(
            """
            SELECT
              COALESCE(sel.name,'') AS vendedor,
              COUNT(*) AS vendas,
              COALESCE(SUM(s.total),0) AS faturamento
            FROM sales s
            LEFT JOIN sellers sel ON sel.id = s.seller_id
            GROUP BY sel.name
            ORDER BY faturamento DESC
            LIMIT 10
            """
        )
        if rows:
            df = pd.DataFrame(rows)
            df["faturamento"] = df["faturamento"].astype(float)
            ch = (
                alt.Chart(df)
                .mark_bar()
                .encode(
                    x=alt.X("faturamento:Q", title="Faturamento (R$)"),
                    y=alt.Y("vendedor:N", sort="-x", title=""),
                    tooltip=["vendedor:N", "vendas:Q", alt.Tooltip("faturamento:Q", format=",.2f")],
                )
                .properties(height=280)
            )
            st.markdown("**Top vendedores (faturamento)**")
            st.altair_chart(ch, use_container_width=True)
        else:
            st.info("Sem vendas ainda.")


# ---------------------------------------------------------------------------
# Prestação de contas por consignante
# ---------------------------------------------------------------------------

def _consignor_settlement() -> None:
    st.subheader("📦 Prestação de contas (consignantes)")
    st.caption("Comparativo: cadastrado x vendido + expectativas x realizado.")

    consignors = query("SELECT id, name FROM consignors WHERE active = TRUE ORDER BY name")
    if not consignors:
        st.info("Nenhum consignante cadastrado.")
        return

    opts = {c["name"]: c["id"] for c in consignors}
    name = st.selectbox("Consignante", list(opts.keys()))
    consignor_id = opts[name]

    # products.initial_stock foi adicionado no patch anterior; se não existir, COALESCE para stock.
    rows = query(
        """
        SELECT
          p.id,
          p.sku,
          p.name AS produto,
          COALESCE(p.initial_stock, p.stock) AS cadastrado,
          p.price,
          COALESCE(p.supplier_unit_cost, 0) AS repasse_unit
        FROM products p
        WHERE p.is_consigned = TRUE AND p.consignor_id = %s
        ORDER BY p.name
        """,
        [consignor_id],
    )
    if not rows:
        st.info("Este consignante não tem produtos consignados cadastrados.")
        return

    df = pd.DataFrame(rows)

    sold = query(
        """
        SELECT
          si.product_id,
          COALESCE(SUM(si.qty),0) AS vendido
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE si.product_id = ANY(%s)
        GROUP BY si.product_id
        """,
        [[int(x) for x in df["id"].tolist()]],
    )
    sold_map = {r["product_id"]: int(r["vendido"]) for r in sold}
    df["vendido"] = df["id"].map(lambda x: sold_map.get(int(x), 0)).astype(int)

    df["exp_faturamento"] = df["price"].astype(float) * df["cadastrado"].astype(int)
    df["exp_repasse"] = df["repasse_unit"].astype(float) * df["cadastrado"].astype(int)
    df["fat_real"] = df["price"].astype(float) * df["vendido"].astype(int)
    df["rep_real"] = df["repasse_unit"].astype(float) * df["vendido"].astype(int)

    out = df[[
        "sku",
        "produto",
        "cadastrado",
        "vendido",
        "price",
        "repasse_unit",
        "exp_faturamento",
        "exp_repasse",
        "fat_real",
        "rep_real",
    ]].rename(
        columns={
            "sku": "SKU",
            "produto": "Produto",
            "cadastrado": "Qtd cadastrada",
            "vendido": "Qtd vendida",
            "price": "Preço unit.",
            "repasse_unit": "Repasse unit.",
            "exp_faturamento": "Expectativa faturamento",
            "exp_repasse": "Expectativa repasse",
            "fat_real": "Faturamento real",
            "rep_real": "Repasse real",
        }
    )

    st.download_button(
        "⬇️ Exportar prestação (Excel)",
        data=df_to_xlsx_bytes(out, "Prestacao"),
        file_name=f"prestacao_{name}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.dataframe(out, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Relatório detalhado (1 linha por item vendido)
# ---------------------------------------------------------------------------

def _sales_items_detail() -> None:
    st.subheader("🧾 Detalhamento (1 linha por item vendido)")
    st.caption("Exportável para Excel. Cada linha é um item de uma venda.")

    rows = query(
        """
        SELECT
            s.id AS venda_id,
            s.created_at AS data_hora,
            COALESCE(sel.name,'') AS vendedor,
            COALESCE(s.buyer_name,'') AS comprador,
            COALESCE(s.buyer_team,'') AS equipe_comprador,
            s.payment_method AS forma_pagamento,
            s.payment_status AS status_pagamento,
            p.sku AS sku,
            p.name AS produto,
            si.qty AS qtd,
            si.unit_price AS preco_unit,
            COALESCE(si.unit_cost, p.unit_cost, 0) AS custo_unit,
            si.line_total AS faturamento_item,
            CASE WHEN p.is_consigned THEN TRUE ELSE FALSE END AS consignado,
            COALESCE(c.name,'') AS consignante,
            COALESCE(p.supplier_unit_cost, 0) AS repasse_unit,
            (COALESCE(p.supplier_unit_cost, 0) * si.qty) AS repasse_total,
            (si.line_total - (COALESCE(si.unit_cost, p.unit_cost, 0) * si.qty)) AS lucro_bruto_item
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        LEFT JOIN sellers sel ON sel.id = s.seller_id
        JOIN products p ON p.id = si.product_id
        LEFT JOIN consignors c ON c.id = p.consignor_id
        ORDER BY s.created_at DESC, s.id DESC
        LIMIT 5000
        """
    )

    if not rows:
        st.info("Sem vendas registradas.")
        return

    df = pd.DataFrame(rows)

    # Excel-safe: utils.df_to_xlsx_bytes já sanitiza TZ.
    st.download_button(
        "⬇️ Exportar detalhamento (Excel)",
        data=df_to_xlsx_bytes(df, "ItensVendidos"),
        file_name="detalhamento_itens_vendidos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.dataframe(df, hide_index=True, use_container_width=True, height=520)
