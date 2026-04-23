"""Dashboard (UX upgrade)

Mudanças:
- Sem filtro de datas (usa tudo que existe no banco)
- KPIs em cards (estilo “print 1”)
- Remove gráfico de evolução do período
- Rankings com visual mais limpo (estilo “print 2”)
- Mantém Prestação de contas (consignantes)
- Adiciona relatório detalhado de itens vendidos (1 linha por item) + export Excel
- Remove relatório de estoque baixo
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
import plotly.express as px

from auth import require_login
from db import query
from utils import df_to_xlsx_bytes, money_fmt


def render() -> None:
    require_login()

    _inject_css()

    st.title("📊 Dashboard")
    st.caption("Resumo geral do Mercadinho (sem filtro de datas).")

    # Período “all time” (sistema rodará por pouco tempo)
    start_ts = datetime(2000, 1, 1)
    end_ts = datetime.utcnow() + timedelta(days=1)

    _kpis_cards(start_ts, end_ts)
    st.divider()

    _rankings_clean(start_ts, end_ts)
    st.divider()

    _consignor_report(start_ts, end_ts)
    st.divider()

    _sales_items_report(start_ts, end_ts)


def _inject_css() -> None:
    st.markdown(
        """
<style>
/* KPI cards */
.kpi-grid{
  display:grid;
  grid-template-columns: repeat(4, minmax(160px, 1fr));
  gap: 14px;
}
@media (max-width: 1200px){
  .kpi-grid{ grid-template-columns: repeat(2, minmax(160px, 1fr)); }
}
.kpi{
  background: #ffffff;
  border: 1px solid rgba(0,0,0,.06);
  border-radius: 16px;
  padding: 14px 14px 12px 14px;
  box-shadow: 0 10px 22px rgba(0,0,0,.05);
}
.kpi-top{
  display:flex;
  align-items:center;
  gap: 10px;
  margin-bottom: 6px;
}
.kpi-ico{
  width: 34px;
  height: 34px;
  border-radius: 12px;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size: 16px;
  background: rgba(17,75,95,.10);
  color: #114B5F;
}
.kpi-title{
  font-size: 13px;
  font-weight: 600;
  color: rgba(0,0,0,.55);
  line-height: 1.1;
}
.kpi-value{
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.02em;
  margin-top: 2px;
}
.kpi-sub{
  margin-top: 4px;
  font-size: 12px;
  color: rgba(0,0,0,.50);
}

/* Chart containers */
.chart-card{
  background: #ffffff;
  border: 1px solid rgba(0,0,0,.06);
  border-radius: 18px;
  padding: 14px 14px 10px 14px;
  box-shadow: 0 10px 22px rgba(0,0,0,.05);
}
.chart-title{
  font-weight: 800;
  margin-bottom: 6px;
}
.chart-sub{
  color: rgba(0,0,0,.55);
  font-size: 12px;
  margin-bottom: 10px;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _kpi_cards(start_ts: datetime, end_ts: datetime) -> None:
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
        SELECT
            COALESCE(SUM(si.qty * (si.unit_price - COALESCE(si.unit_cost, 0))), 0) AS gross_profit,
            COALESCE(SUM(si.line_total), 0) AS gross_revenue
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE s.created_at >= %s AND s.created_at < %s
          AND s.payment_status = 'PAGO'
        """,
        [start_ts, end_ts],
    )[0]

    revenue = float(r.get("revenue") or 0)
    sales_count = int(r.get("sales_count") or 0)
    ticket = float(r.get("ticket_avg") or 0)
    open_total = float(r.get("open_total") or 0)
    open_count = int(r.get("open_count") or 0)

    gross_profit = float(profit_row.get("gross_profit") or 0)
    gross_rev = float(profit_row.get("gross_revenue") or 0)
    margin = (gross_profit / gross_rev * 100) if gross_rev > 0 else 0.0
    cost_total = max(gross_rev - gross_profit, 0.0)

    st.markdown(
        f"""
<div class="kpi-grid">
  {_kpi_html("💰","Faturamento", money_fmt(revenue), "Total vendido")}
  {_kpi_html("🧾","Vendas", f"{sales_count}", "Quantidade de cupons")}
  {_kpi_html("🎟️","Ticket médio", money_fmt(ticket), "Média por venda")}
  {_kpi_html("⏳","Em aberto (Fiado)", money_fmt(open_total), f"{open_count} venda(s)")}
</div>
<br/>
<div class="kpi-grid" style="grid-template-columns: repeat(2, minmax(160px, 1fr));">
  {_kpi_html("📈","Lucro bruto (pagos)", money_fmt(gross_profit), f"Margem: {margin:,.1f}%".replace(",", "X").replace(".", ",").replace("X","."))}
  {_kpi_html("🧮","Custo estimado (pagos)", money_fmt(cost_total), "Custo total (unitário x qtd)")}
</div>
        """,
        unsafe_allow_html=True,
    )


def _kpi_html(icon: str, title: str, value: str, sub: str) -> str:
    return (
        f"<div class='kpi'>"
        f"  <div class='kpi-top'>"
        f"    <div class='kpi-ico'>{icon}</div>"
        f"    <div class='kpi-title'>{title}</div>"
        f"  </div>"
        f"  <div class='kpi-value'>{value}</div>"
        f"  <div class='kpi-sub'>{sub}</div>"
        f"</div>"
    )


def _rankings_clean(start_ts: datetime, end_ts: datetime) -> None:
    st.subheader("🏆 Rankings")

    c1, c2 = st.columns(2)

    df_prod = pd.DataFrame(
        query(
            """
            SELECT
              p.name AS produto,
              p.sku AS sku,
              COALESCE(SUM(si.qty),0) AS qtd,
              COALESCE(SUM(si.line_total),0) AS faturamento
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            JOIN products p ON p.id = si.product_id
            WHERE s.created_at >= %s AND s.created_at < %s
            GROUP BY p.id
            ORDER BY faturamento DESC
            LIMIT 10
            """,
            [start_ts, end_ts],
        )
    )

    df_sell = pd.DataFrame(
        query(
            """
            SELECT
              COALESCE(se.name, '—') AS vendedor,
              COUNT(*) AS vendas,
              COALESCE(SUM(s.total),0) AS faturamento
            FROM sales s
            LEFT JOIN sellers se ON se.id = s.seller_id
            WHERE s.created_at >= %s AND s.created_at < %s
            GROUP BY vendedor
            ORDER BY faturamento DESC
            LIMIT 10
            """,
            [start_ts, end_ts],
        )
    )

    with c1:
        st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
        st.markdown("<div class='chart-title'>Top produtos (faturamento)</div>", unsafe_allow_html=True)
        st.markdown("<div class='chart-sub'>Barras horizontais • valores fora da barra</div>", unsafe_allow_html=True)
        if df_prod.empty:
            st.info("Sem dados ainda.")
        else:
            dfp = df_prod.sort_values("faturamento", ascending=True)
            fig = px.bar(dfp, x="faturamento", y="produto", orientation="h", text="faturamento")
            fig.update_traces(
                marker_color="#114B5F",
                texttemplate="R$ %{x:,.2f}",
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                height=360,
                margin=dict(l=10, r=34, t=0, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
            )
            fig.update_xaxes(showgrid=False, zeroline=False, visible=False)
            fig.update_yaxes(showgrid=False, ticks="", title=None)
            st.plotly_chart(fig, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown("<div class='chart-card'>", unsafe_allow_html=True)
        st.markdown("<div class='chart-title'>Ranking vendedores (faturamento)</div>", unsafe_allow_html=True)
        st.markdown("<div class='chart-sub'>Total vendido por vendedor</div>", unsafe_allow_html=True)
        if df_sell.empty:
            st.info("Sem dados ainda.")
        else:
            dfs = df_sell.sort_values("faturamento", ascending=True)
            fig = px.bar(dfs, x="faturamento", y="vendedor", orientation="h", text="faturamento")
            fig.update_traces(
                marker_color="#1A936F",
                texttemplate="R$ %{x:,.2f}",
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                height=360,
                margin=dict(l=10, r=34, t=0, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
            )
            fig.update_xaxes(showgrid=False, zeroline=False, visible=False)
            fig.update_yaxes(showgrid=False, ticks="", title=None)
            st.plotly_chart(fig, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)


def _sales_items_report(start_ts: datetime, end_ts: datetime) -> None:
    st.subheader("🧾 Detalhamento de itens vendidos")
    st.caption("1 linha por item vendido (venda + produto + consignante).")

    rows = query(
        """
        SELECT
            s.id AS venda_id,
            s.created_at AS data_hora,
            COALESCE(se.name, '—') AS vendedor,
            COALESCE(s.buyer_name, '') AS comprador,
            COALESCE(s.buyer_team, '') AS equipe_comprador,
            s.payment_method AS forma_pagamento,
            s.payment_status AS status_pagamento,

            p.sku AS sku,
            p.name AS produto,
            si.qty AS qtd,
            si.unit_price AS preco_unit,
            COALESCE(si.unit_cost, p.unit_cost, 0) AS custo_unit,
            si.line_total AS faturamento_item,

            CASE WHEN p.is_consigned THEN 'Consignado' ELSE 'Padrão' END AS tipo,
            COALESCE(cg.name,'') AS consignante,
            COALESCE(p.supplier_unit_cost, 0) AS repasse_unit,
            (COALESCE(p.supplier_unit_cost, 0) * si.qty) AS repasse_total
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        LEFT JOIN sellers se ON se.id = s.seller_id
        JOIN products p ON p.id = si.product_id
        LEFT JOIN consignors cg ON cg.id = p.consignor_id
        WHERE s.created_at >= %s AND s.created_at < %s
        ORDER BY s.created_at DESC, s.id DESC, si.id DESC
        """,
        [start_ts, end_ts],
    )

    df = pd.DataFrame(rows)

    if df.empty:
        st.info("Sem itens vendidos ainda.")
        return

    st.download_button(
        "⬇️ Exportar itens vendidos (Excel)",
        data=df_to_xlsx_bytes(df, "ItensVendidos"),
        file_name="itens_vendidos_detalhado.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.dataframe(df, use_container_width=True, height=520)


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
