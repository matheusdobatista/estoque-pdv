"""Produtos — CRUD."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import has_role, require_login
from db import execute, execute_returning, get_conn, query, query_one
from utils import df_to_xlsx_bytes, money_fmt, next_sku_default


def render() -> None:
    user = require_login()
    can_write = has_role(user, {"ADMIN", "OPERADOR"})
    can_delete = has_role(user, {"ADMIN"})

    st.title("📦 Produtos")

    tabs = st.tabs(["📋 Lista", "➕ Novo"] if can_write else ["📋 Lista"])

    with tabs[0]:
        _tab_list(user, can_write=can_write, can_delete=can_delete)

    if can_write:
        with tabs[1]:
            _tab_new(user)


# ---------------------------------------------------------------------------
# Lista
# ---------------------------------------------------------------------------

def _tab_list(user, *, can_write: bool, can_delete: bool) -> None:
    rows = query("""
        SELECT p.id, p.sku, p.name, p.price, p.unit_cost, p.stock, p.initial_stock, p.min_stock,
               p.active, p.is_consigned, p.supplier_unit_cost,
               c.name AS consignor_name
        FROM products p
        LEFT JOIN consignors c ON c.id = p.consignor_id
        ORDER BY p.name
    """)
    df = pd.DataFrame(rows)

    f1, f2, f3 = st.columns([2, 1, 1])
    term = f1.text_input("🔎 Buscar (nome ou SKU)", "")
    only_active = f2.checkbox("Somente ativos", value=True)
    low_stock = f3.checkbox("Só estoque baixo", value=False)

    if df.empty:
        st.info("Nenhum produto cadastrado.")
        return

    view = df.copy()
    if term:
        t = term.lower()
        view = view[view["name"].str.lower().str.contains(t) | view["sku"].str.lower().str.contains(t)]
    if only_active:
        view = view[view["active"] == True]  # noqa: E712
    if low_stock:
        view = view[view["stock"] <= view["min_stock"]]

    st.caption(f"{len(view)} produto(s)")

    display = view[[
        "sku", "name", "price", "unit_cost", "stock", "initial_stock", "min_stock",
        "is_consigned", "consignor_name", "active",
    ]].rename(columns={
        "sku": "SKU", "name": "Nome", "price": "Preço", "unit_cost": "Custo",
        "stock": "Estoque", "initial_stock": "Inicial", "min_stock": "Mín", "is_consigned": "Consig.",
        "consignor_name": "Consignante", "active": "Ativo",
    })
    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Preço": st.column_config.NumberColumn(format="R$ %.2f"),
            "Custo": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

    st.download_button(
        "⬇️ Exportar Excel",
        data=df_to_xlsx_bytes(view, "Produtos"),
        file_name="produtos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    if not can_write:
        return

    st.divider()
    st.subheader("Editar produto")
    options = {"— Selecione —": None}
    for _, r in view.iterrows():
        options[f"{r['sku']} — {r['name']}"] = int(r["id"])
    picked_label = st.selectbox("Produto", list(options.keys()))
    picked_id = options.get(picked_label)
    if picked_id:
        _edit_form(user, picked_id, can_delete=can_delete)


# ---------------------------------------------------------------------------
# Novo
# ---------------------------------------------------------------------------

def _tab_new(user) -> None:
    consignors = query("SELECT id, name FROM consignors WHERE active = TRUE ORDER BY name")
    cons_opts = {"— Nenhum —": None}
    for c in consignors:
        cons_opts[c["name"]] = c["id"]

    c1, c2 = st.columns([3, 1])
    name = c1.text_input("Nome*", key="newp_name")
    sku = c2.text_input("SKU", value=next_sku_default(), key="newp_sku")

    c3, c4, c5 = st.columns(3)
    price = c3.number_input("Preço (R$)*", min_value=0.0, step=0.5, format="%.2f", key="newp_price")
    unit_cost = c4.number_input("Custo unitário (R$)", min_value=0.0, step=0.5, format="%.2f", key="newp_unit_cost")
    stock = c5.number_input("Estoque inicial", min_value=0, step=1, value=0, key="newp_stock")

    c6, c7 = st.columns(2)
    min_stock = c6.number_input("Estoque mínimo", min_value=0, step=1, value=5, key="newp_min_stock")
    is_consigned = c7.checkbox("Produto consignado?", value=False, key="newp_is_consigned")

    c8, c9 = st.columns(2)
    consignor_label = c8.selectbox(
        "Consignante",
        list(cons_opts.keys()),
        disabled=not is_consigned,
        key="newp_consignor_label",
    )
    supplier_cost = c9.number_input(
        "Repasse ao consignante (R$)",
        min_value=0.0, step=0.5, format="%.2f",
        disabled=not is_consigned,
        key="newp_supplier_cost",
    )

    submit = st.button("Cadastrar", type="primary", use_container_width=True, key="newp_submit")

    if submit:
        if not name.strip():
            st.error("Nome é obrigatório.")
            return
        if not sku.strip():
            st.error("SKU é obrigatório.")
            return
        if price <= 0:
            st.error("Preço deve ser maior que zero.")
            return
        if is_consigned and cons_opts.get(consignor_label) is None:
            st.error("Selecione um consignante.")
            return

        query(
            "INSERT INTO products "
            "(name, sku, price, unit_cost, stock, initial_stock, min_stock, is_consigned, "
            " consignor_id, supplier_unit_cost) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                name.strip(),
                sku.strip(),
                float(price),
                float(unit_cost) if unit_cost and unit_cost > 0 else None,
                int(stock),
                int(stock),
                int(min_stock),
                bool(is_consigned),
                cons_opts.get(consignor_label) if is_consigned else None,
                (float(supplier_cost) if supplier_cost and supplier_cost > 0 else None) if is_consigned else None,
            ],
        )
        st.success("Produto cadastrado.")
        st.rerun()

