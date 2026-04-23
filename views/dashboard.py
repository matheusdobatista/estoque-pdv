"""Dashboard gerencial."""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from auth import require_login
from db import query
from utils import df_to_xlsx_bytes, money_fmt


# ---------------------------------------------------------------------------
# Render principal
# ---------------------------------------------------------------------------

def render() -> None:
    require_login()
    _inject_dashboard_css()

    st.title("📊 Dashboard")
    st.caption("Visão consolidada do período de uso do sistema. Sem filtro de data.")

    _kpis()
    st.divider()
    _rankings()
    st.divider()
    _consignor_report()
    st.divider()
    _sales_detail_report()


# ---------------------------------------------------------------------------
# Estilo
# ---------------------------------------------------------------------------

def _inject_dashboard_css() -> None:
    st.markdown(
        """
        <style>
            .dash-section-title {
                font-size: 1.15rem;
                font-weight: 700;
                color: #0F172A;
                margin-bottom: 0.3rem;
            }
            .dash-section-subtitle {
                color: #64748B;
                font-size: 0.93rem;
                margin-bottom: 1rem;
            }
            .dash-card {
                background: linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%);
                border: 1px solid #E2E8F0;
                border-radius: 18px;
                padding: 1rem 1.1rem;
                box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
                min-height: 132px;
                position: relative;
                overflow: hidden;
            }
            .dash-card::after {
                content: "";
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 4px;
                background: var(--accent-color, #14B8A6);
            }
            .dash-card-top {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 0.7rem;
            }
            .dash-icon {
                width: 36px;
                height: 36px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1rem;
                background: var(--accent-soft, #CCFBF1);
            }
            .dash-card-label {
                font-size: 0.85rem;
                color: #64748B;
                margin-bottom: 0.35rem;
                line-height: 1.2;
            }
            .dash-card-value {
                font-size: 1.8rem;
                line-height: 1.1;
                font-weight: 800;
                color: #0F172A;
                margin-bottom: 0.35rem;
            }
            .dash-card-foot {
                font-size: 0.84rem;
                color: #475569;
                line-height: 1.35;
            }
            .dash-block {
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 18px;
                padding: 1rem 1rem 0.75rem 1rem;
                box-shadow: 0 6px 18px rgba(15, 23, 42, 0.05);
                margin-bottom: 1rem;
            }
            .dash-note {
                color: #64748B;
                font-size: 0.88rem;
                margin-top: -0.4rem;
                margin-bottom: 0.6rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

def _kpis() -> None:
    r = query(
        """
        SELECT
            COUNT(*) AS sales_count,
            COALESCE(SUM(total), 0) AS revenue,
            COALESCE(AVG(total), 0) AS ticket_avg,
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

    st.markdown('<div class="dash-section-title">Resumo geral</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="dash-section-subtitle">Indicadores consolidados de vendas, resultado e fiado.</div>',
        unsafe_allow_html=True,
    )

    row1 = st.columns(3)
    row2 = st.columns(3)

    _metric_card(
        row1[0],
        title="Faturamento",
        value=money_fmt(r["revenue"]),
        foot="Valor total vendido no período do evento.",
        icon="💰",
        accent="#14B8A6",
        soft="#CCFBF1",
    )
    _metric_card(
        row1[1],
        title="Vendas",
        value=f"{int(r['sales_count'] or 0)}",
        foot="Quantidade total de vendas registradas.",
        icon="🧾",
        accent="#8B5CF6",
        soft="#EDE9FE",
    )
    _metric_card(
        row1[2],
        title="Ticket médio",
        value=money_fmt(r["ticket_avg"]),
        foot="Média de valor por venda realizada.",
        icon="🛍️",
        accent="#F59E0B",
        soft="#FEF3C7",
    )
    _metric_card(
        row2[0],
        title="Lucro bruto (pagos)",
        value=money_fmt(gross_profit),
        foot="Receita paga menos custo dos itens vendidos.",
        icon="📈",
        accent="#22C55E",
        soft="#DCFCE7",
    )
    _metric_card(
        row2[1],
        title="Margem",
        value=f"{margin:.1f}%",
        foot="Margem bruta calculada sobre vendas pagas.",
        icon="📊",
        accent="#0EA5E9",
        soft="#E0F2FE",
    )
    _metric_card(
        row2[2],
        title="Em aberto (fiado)",
        value=money_fmt(r["open_total"]),
        foot=f"{int(r['open_count'] or 0)} venda(s) ainda em aberto.",
        icon="⏳",
        accent="#EF4444",
        soft="#FEE2E2",
    )


def _metric_card(col, title: str, value: str, foot: str, icon: str, accent: str, soft: str) -> None:
    col.markdown(
        f"""
        <div class="dash-card" style="--accent-color:{accent}; --accent-soft:{soft};">
            <div class="dash-card-top">
                <div class="dash-card-label">{title}</div>
                <div class="dash-icon">{icon}</div>
            </div>
            <div class="dash-card-value">{value}</div>
            <div class="dash-card-foot">{foot}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Rankings
# ---------------------------------------------------------------------------

def _rankings() -> None:
    st.markdown('<div class="dash-section-title">Rankings</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="dash-section-subtitle">Visual dos rankings em barras horizontais, com foco em leitura rápida.</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)

    with left:
        st.markdown('<div class="dash-block">', unsafe_allow_html=True)
        st.subheader("Top produtos")
        st.caption("Ranking por faturamento dos itens vendidos.")
        rows = query(
            """
            SELECT
                p.name,
                SUM(si.qty) AS qty,
                SUM(si.line_total) AS revenue
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            JOIN products p ON p.id = si.product_id
            GROUP BY p.name
            ORDER BY revenue DESC
            LIMIT 10
            """
        )
        if rows:
            df = pd.DataFrame(rows)
            df["revenue"] = df["revenue"].astype(float)
            df["qty"] = df["qty"].astype(int)
            _horizontal_bar_chart(
                df,
                category_col="name",
                value_col="revenue",
                value_title="Faturamento",
                color="#14B8A6",
            )
            table_df = df.rename(columns={"name": "Produto", "qty": "Qtd", "revenue": "Faturamento"})
            st.dataframe(
                table_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Faturamento": st.column_config.NumberColumn(format="R$ %.2f"),
                },
            )
        else:
            st.info("Sem dados de produtos vendidos.")
        st.markdown('</div>', unsafe_allow_html=True)

    with right:
        st.markdown('<div class="dash-block">', unsafe_allow_html=True)
        st.subheader("Top vendedores")
        st.caption("Ranking por faturamento das vendas registradas.")
        rows = query(
            """
            SELECT
                COALESCE(sl.name, '(sem vendedor)') AS seller,
                COUNT(*) AS sales,
                SUM(s.total) AS revenue
            FROM sales s
            LEFT JOIN sellers sl ON sl.id = s.seller_id
            GROUP BY sl.name
            ORDER BY revenue DESC
            LIMIT 10
            """
        )
        if rows:
            df = pd.DataFrame(rows)
            df["revenue"] = df["revenue"].astype(float)
            df["sales"] = df["sales"].astype(int)
            _horizontal_bar_chart(
                df,
                category_col="seller",
                value_col="revenue",
                value_title="Faturamento",
                color="#8B5CF6",
            )
            table_df = df.rename(columns={"seller": "Vendedor", "sales": "Vendas", "revenue": "Faturamento"})
            st.dataframe(
                table_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Faturamento": st.column_config.NumberColumn(format="R$ %.2f"),
                },
            )
        else:
            st.info("Sem dados de vendedores.")
        st.markdown('</div>', unsafe_allow_html=True)


def _horizontal_bar_chart(
    df: pd.DataFrame,
    category_col: str,
    value_col: str,
    value_title: str,
    color: str,
) -> None:
    plot_df = df.copy().sort_values(value_col, ascending=False).head(10)
    plot_df["label"] = plot_df[value_col].apply(money_fmt)

    base = alt.Chart(plot_df).encode(
        y=alt.Y(
            f"{category_col}:N",
            sort=alt.EncodingSortField(field=value_col, order="descending"),
            title=None,
            axis=alt.Axis(labelFontSize=12, labelLimit=220, ticks=False, domain=False),
        ),
        x=alt.X(
            f"{value_col}:Q",
            title=None,
            axis=alt.Axis(labels=False, ticks=False, domain=False, grid=False),
        ),
    )

    bars = base.mark_bar(cornerRadiusEnd=8, size=26, color=color).encode(
        tooltip=[
            alt.Tooltip(f"{category_col}:N", title="Item"),
            alt.Tooltip(f"{value_col}:Q", title=value_title, format=",.2f"),
        ]
    )

    text = base.mark_text(
        align="left",
        baseline="middle",
        dx=8,
        color="#334155",
        fontSize=12,
        fontWeight="bold",
    ).encode(text="label:N")

    chart = (bars + text).properties(height=max(260, len(plot_df) * 34))
    st.altair_chart(chart, use_container_width=True)


# ---------------------------------------------------------------------------
# Prestação de contas (Consignantes) - mantido
# ---------------------------------------------------------------------------

def _consignor_report() -> None:
    st.markdown('<div class="dash-section-title">Prestação de contas — Consignantes</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="dash-section-subtitle">Comparativo por produto: cadastrado inicialmente x vendido, com faturamento e repasse.</div>',
        unsafe_allow_html=True,
    )

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
        WHERE p.is_consigned = TRUE
          AND p.consignor_id = %s
          AND (
                s.id IS NULL
                OR s.id IN (SELECT id FROM sales)
              )
        GROUP BY p.sku, p.name, p.initial_stock, p.price, p.supplier_unit_cost
        ORDER BY p.name
        """,
        [consignor_id],
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
# Relatório detalhado de vendas
# ---------------------------------------------------------------------------

def _sales_detail_report() -> None:
    st.markdown('<div class="dash-section-title">Relatório detalhado de vendas</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="dash-section-subtitle">Cada linha representa um item vendido dentro de uma venda. Ideal para auditoria e exportação.</div>',
        unsafe_allow_html=True,
    )

    rows = query(
        """
        SELECT
            s.id AS venda,
            s.created_at,
            COALESCE(sl.name, '(sem vendedor)') AS vendedor,
            COALESCE(s.buyer_name, '') AS comprador,
            COALESCE(s.buyer_team, '') AS equipe,
            s.payment_method AS forma_pagamento,
            s.payment_status AS status_pagamento,
            s.total AS total_venda,
            p.sku,
            p.name AS produto,
            si.qty AS quantidade,
            COALESCE(si.unit_cost, 0)::numeric(12,2) AS custo_unitario,
            CASE WHEN p.is_consigned THEN 'Sim' ELSE 'Não' END AS consignado,
            COALESCE(c.name, '') AS consignante,
            si.unit_price::numeric(12,2) AS preco_unitario,
            si.line_total::numeric(12,2) AS faturamento_item,
            (COALESCE(si.unit_cost, 0) * si.qty)::numeric(12,2) AS valor_repasse,
            ((si.unit_price - COALESCE(si.unit_cost, 0)) * si.qty)::numeric(12,2) AS lucro_bruto_item
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        JOIN products p ON p.id = si.product_id
        LEFT JOIN sellers sl ON sl.id = s.seller_id
        LEFT JOIN consignors c ON c.id = p.consignor_id
        ORDER BY s.created_at DESC, s.id DESC, p.name
        """
    )

    if not rows:
        st.info("Nenhuma venda registrada até o momento.")
        return

    df = pd.DataFrame(rows)
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["Data/Hora"] = df["created_at"].dt.strftime("%d/%m/%Y %H:%M")

    for col in ["total_venda", "custo_unitario", "preco_unitario", "faturamento_item", "valor_repasse", "lucro_bruto_item"]:
        df[col] = df[col].astype(float)
    df["quantidade"] = df["quantidade"].astype(int)

    show = df[[
        "venda", "Data/Hora", "vendedor", "comprador", "equipe",
        "forma_pagamento", "status_pagamento", "total_venda",
        "sku", "produto", "quantidade", "custo_unitario",
        "consignado", "consignante", "preco_unitario",
        "faturamento_item", "valor_repasse", "lucro_bruto_item",
    ]].rename(columns={
        "venda": "Venda",
        "vendedor": "Vendedor",
        "comprador": "Comprador",
        "equipe": "Equipe",
        "forma_pagamento": "Forma de pagamento",
        "status_pagamento": "Status",
        "total_venda": "Total da venda",
        "sku": "SKU",
        "produto": "Produto",
        "quantidade": "Qtd",
        "custo_unitario": "Custo unitário",
        "consignado": "Consignado",
        "consignante": "Consignante",
        "preco_unitario": "Preço unitário",
        "faturamento_item": "Faturamento item",
        "valor_repasse": "Valor de repasse",
        "lucro_bruto_item": "Lucro bruto item",
    })

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Itens vendidos", f"{int(show['Qtd'].sum())}")
    c2.metric("Linhas no relatório", f"{len(show)}")
    c3.metric("Faturamento dos itens", money_fmt(show["Faturamento item"].sum()))
    c4.metric("Repasse dos itens", money_fmt(show["Valor de repasse"].sum()))

    st.download_button(
        "⬇️ Exportar relatório detalhado (Excel)",
        data=df_to_xlsx_bytes(show, "VendasDetalhadas"),
        file_name="relatorio_detalhado_vendas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.dataframe(
        show,
        hide_index=True,
        use_container_width=True,
        height=460,
        column_config={
            "Total da venda": st.column_config.NumberColumn(format="R$ %.2f"),
            "Custo unitário": st.column_config.NumberColumn(format="R$ %.2f"),
            "Preço unitário": st.column_config.NumberColumn(format="R$ %.2f"),
            "Faturamento item": st.column_config.NumberColumn(format="R$ %.2f"),
            "Valor de repasse": st.column_config.NumberColumn(format="R$ %.2f"),
            "Lucro bruto item": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )
