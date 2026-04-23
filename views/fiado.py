"""
Fiado — vendas com payment_status = 'ABERTO'.
Permite marcar como pago, alterando forma de pagamento e calculando troco.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import has_role, require_login
from db import query, query_one, transaction
from utils import df_to_xlsx_bytes, fmt_ts, money_fmt, PAYMENT_METHODS


def render() -> None:
    user = require_login()
    can_settle = has_role(user, {"ADMIN", "OPERADOR"})

    st.title("💳 Fiado — Vendas em Aberto")

    open_sales = query("""
        SELECT s.id, s.created_at, s.buyer_name, s.buyer_team, s.total,
               sl.name AS seller_name
        FROM sales s
        LEFT JOIN sellers sl ON sl.id = s.seller_id
        WHERE s.payment_status = 'ABERTO'
        ORDER BY s.created_at DESC
    """)

    if not open_sales:
        st.success("🎉 Nenhuma venda em aberto.")
        return

    total_open = sum(float(s["total"]) for s in open_sales)
    k1, k2 = st.columns(2)
    k1.metric("Vendas em aberto", len(open_sales))
    k2.metric("Valor total pendente", money_fmt(total_open))

    st.divider()

    df = pd.DataFrame(open_sales)
    df["created_at"] = df["created_at"].apply(fmt_ts)
    df = df.rename(columns={
        "id": "#", "created_at": "Data", "buyer_name": "Comprador",
        "buyer_team": "Equipe", "seller_name": "Vendedor", "total": "Total",
    })
    st.dataframe(
        df[["#", "Data", "Comprador", "Equipe", "Vendedor", "Total"]],
        hide_index=True,
        use_container_width=True,
        column_config={"Total": st.column_config.NumberColumn(format="R$ %.2f")},
    )

    st.download_button(
        "⬇️ Exportar Excel",
        data=df_to_xlsx_bytes(df, "Fiado"),
        file_name="fiado_aberto.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if not can_settle:
        return

    st.divider()
    st.subheader("Registrar pagamento")

    opts = {"— Selecione —": None}
    for s in open_sales:
        buyer = s["buyer_name"] or "(sem nome)"
        opts[f"#{s['id']} • {buyer} ({s['buyer_team']}) • {money_fmt(s['total'])}"] = s["id"]
    label = st.selectbox("Venda", list(opts.keys()))
    sale_id = opts.get(label)

    if not sale_id:
        return

    sale = query_one("SELECT * FROM sales WHERE id = %s", [sale_id])
    st.info(
        f"Venda **#{sale['id']}** — Total: **{money_fmt(sale['total'])}** — "
        f"Comprador: {sale['buyer_name'] or '—'} ({sale['buyer_team']})"
    )

    with st.form(f"settle_{sale_id}"):
        methods = [m for m in PAYMENT_METHODS if m != "Fiado"]
        method = st.selectbox("Nova forma de pagamento*", methods)
        paid = st.number_input(
            "Valor pago (R$)*", min_value=0.0, value=float(sale["total"]), step=1.0, format="%.2f",
        )
        change = max(paid - float(sale["total"]), 0.0)
        st.caption(f"Troco: **{money_fmt(change)}**")
        submit = st.form_submit_button("✅ Confirmar pagamento", type="primary", use_container_width=True)

    if submit:
        if paid < float(sale["total"]):
            st.error(f"Valor pago menor que o total ({money_fmt(sale['total'])}).")
            return

        with transaction() as conn:
            conn.execute(
                "UPDATE sales SET payment_status='PAGO', payment_method=%s, "
                "paid=%s, change_amount=%s, paid_at=NOW(), paid_by_user_id=%s "
                "WHERE id=%s",
                [method, paid, change, user.id, sale_id],
            )
            audit_log(user, "SALE_SETTLE", "sale", sale_id,
                      {"method": method, "paid": paid, "change": change},
                      conn=conn)

        st.success(f"✅ Venda #{sale_id} quitada.")
        st.rerun()
