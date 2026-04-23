"""
Dashboard gerencial.
Versão inicial: KPIs principais + gráficos de evolução e rankings.
(Será expandido no próximo turno com mais detalhes.)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
    _consignor_report(start_ts, end_ts)
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

    st.subheader("Evolução no período")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=df["day"],
            y=df["sales_count"],
            name="Vendas (qtd)",
            marker_color="#0F766E",
            opacity=0.85,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df["day"],
            y=df["revenue"],
            name="Faturamento (R$)",
            mode="lines+markers",
            line=dict(color="#14B8A6", width=3),
            marker=dict(size=6),
        ),
        secondary_y=True,
    )
    fig.update_layout(
        height=360,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Qtd de vendas", secondary_y=False, showgrid=True, gridcolor="rgba(2,6,23,0.06)")
    fig.update_yaxes(title_text="Faturamento (R$)", secondary_y=True, showgrid=False)
    st.plotly_chart(fig, use_container_width=True)



# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------

def _rankings(start_ts: datetime, end_ts: datetime) -> None:
    left, right = st.columns(2)

    with left:
        st.subheader("Top produtos (receita)")
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
            fig = px.bar(
                df.sort_values("revenue", ascending=True),
                x="revenue",
                y="name",
                orientation="h",
                text="revenue",
                labels={"revenue": "Receita (R$)", "name": ""},
                color_discrete_sequence=["#14B8A6"],
            )
            fig.update_traces(texttemplate="R$ %{text:,.2f}", textposition="outside", cliponaxis=False)
            fig.update_layout(
                height=360,
                margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor="white",
                paper_bgcolor="white",
                yaxis=dict(tickfont=dict(size=12)),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                df.rename(columns={"name": "Produto", "qty": "Qtd", "revenue": "Receita"}),
                hide_index=True,
                use_container_width=True,
                column_config={"Receita": st.column_config.NumberColumn(format="R$ %.2f")},
            )
        else:
            st.caption("Sem dados.")

    with right:
        st.subheader("Top vendedores (receita)")
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
            fig = px.bar(
                df.sort_values("revenue", ascending=True),
                x="revenue",
                y="seller",
                orientation="h",
                text="revenue",
                labels={"revenue": "Receita (R$)", "seller": ""},
                color_discrete_sequence=["#0F766E"],
            )
            fig.update_traces(texttemplate="R$ %{text:,.2f}", textposition="outside", cliponaxis=False)
            fig.update_layout(
                height=360,
                margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor="white",
                paper_bgcolor="white",
                yaxis=dict(tickfont=dict(size=12)),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(
                df.rename(columns={"seller": "Vendedor", "sales": "Vendas", "revenue": "Receita"}),
                hide_index=True,
                use_container_width=True,
                column_config={"Receita": st.column_config.NumberColumn(format="R$ %.2f")},
            )
        else:
            st.caption("Sem dados.")





# ---------------------------------------------------------------------------
# Prestação de contas (Consignantes)
# ---------------------------------------------------------------------------

def _consignor_report(start_ts: datetime, end_ts: datetime) -> None:
    st.subheader("📄 Prestação de contas — Consignantes")
    st.caption("Comparativo por produto: cadastrado (inicial) × vendido no período, com faturamento e repasse.")

    cons = query("SELECT id, name, active FROM consignors ORDER BY active DESC, name")
    if not cons:
        st.info("Nenhum consignante cadastrado.")
        return

    opts = {"— Selecione —": None}
    for c in cons:
        label = c["name"] + (" (inativo)" if not c.get("active", True) else "")
        opts[label] = c["id"]

    picked = st.selectbox("Consignante", list(opts.keys()), key="dash_consignor_pick")
    consignor_id = opts.get(picked)
    if not consignor_id:
        st.info("Selecione um consignante para gerar o relatório.")
        return

    rows = query(
        """
        SELECT
          p.sku,
          p.name AS produto,
          COALESCE(p.initial_stock, 0) AS qtd_inicial,
          p.price::numeric(12,2) AS preco_unit,
          COALESCE(p.supplier_unit_cost, 0)::numeric(12,2) AS repasse_unit,
          COALESCE(SUM(si.qty), 0) AS qtd_vendida,
          COALESCE(SUM(si.line_total), 0)::numeric(12,2) AS faturamento_real
        FROM products p
        LEFT JOIN sale_items si ON si.product_id = p.id
        LEFT JOIN sales s ON s.id = si.sale_id
                      AND s.created_at >= %s AND s.created_at < %s
        WHERE p.is_consigned = TRUE
          AND p.consignor_id = %s
        GROUP BY p.sku, p.name, p.initial_stock, p.price, p.supplier_unit_cost
        ORDER BY p.name
        """,
        [start_ts, end_ts, consignor_id],
    )

    if not rows:
        st.warning("Nenhum produto consignado encontrado para este consignante.")
        return

    df = pd.DataFrame(rows)
    df["qtd_inicial"] = df["qtd_inicial"].fillna(0).astype(int)
    df["qtd_vendida"] = df["qtd_vendida"].fillna(0).astype(int)
    df["preco_unit"] = df["preco_unit"].astype(float)
    df["repasse_unit"] = df["repasse_unit"].astype(float)
    df["faturamento_real"] = df["faturamento_real"].astype(float)

    df["exp_faturamento"] = df["preco_unit"] * df["qtd_inicial"]
    df["exp_repasse"] = df["repasse_unit"] * df["qtd_inicial"]
    df["repasse_real"] = df["repasse_unit"] * df["qtd_vendida"]
    df["saldo_qtd"] = df["qtd_inicial"] - df["qtd_vendida"]

    show = df[[
        "sku", "produto",
        "qtd_inicial", "qtd_vendida", "saldo_qtd",
        "preco_unit", "exp_faturamento", "faturamento_real",
        "repasse_unit", "exp_repasse", "repasse_real",
    ]].rename(columns={
        "sku": "SKU",
        "produto": "Produto",
        "qtd_inicial": "Qtd inicial",
        "qtd_vendida": "Qtd vendida",
        "saldo_qtd": "Saldo (qtd)",
        "preco_unit": "Preço unit.",
        "exp_faturamento": "Expectativa fatur.",
        "faturamento_real": "Faturamento real",
        "repasse_unit": "Repasse unit.",
        "exp_repasse": "Expectativa repasse",
        "repasse_real": "Repasse real",
    })

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Faturamento real", money_fmt(show["Faturamento real"].sum()))
    c2.metric("Repasse real", money_fmt(show["Repasse real"].sum()))
    c3.metric("Expectativa fatur.", money_fmt(show["Expectativa fatur."].sum()))
    c4.metric("Expectativa repasse", money_fmt(show["Expectativa repasse"].sum()))

    st.dataframe(
        show,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Preço unit.": st.column_config.NumberColumn(format="R$ %.2f"),
            "Expectativa fatur.": st.column_config.NumberColumn(format="R$ %.2f"),
            "Faturamento real": st.column_config.NumberColumn(format="R$ %.2f"),
            "Repasse unit.": st.column_config.NumberColumn(format="R$ %.2f"),
            "Expectativa repasse": st.column_config.NumberColumn(format="R$ %.2f"),
            "Repasse real": st.column_config.NumberColumn(format="R$ %.2f"),
        },
        height=420,
    )

    st.download_button(
        "⬇️ Exportar prestação de contas (Excel)",
        data=df_to_xlsx_bytes(show, "PrestacaoConsignante"),
        file_name=f"prestacao_consignante_{consignor_id}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
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
