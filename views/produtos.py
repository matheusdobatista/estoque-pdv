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
        SELECT p.id, p.sku, p.name, p.price, p.unit_cost, p.stock, p.min_stock,
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
        "sku", "name", "price", "unit_cost", "stock", "min_stock",
        "is_consigned", "consignor_name", "active",
    ]].rename(columns={
        "sku": "SKU", "name": "Nome", "price": "Preço", "unit_cost": "Custo",
        "stock": "Estoque", "min_stock": "Mín", "is_consigned": "Consig.",
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

    # NÃO usar st.form aqui: checkbox/selectbox precisam re-renderizar ao marcar "consignado".
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
        key="newp_consignor",
    )
    supplier_cost = c9.number_input(
        "Repasse ao consignante (R$)",
        min_value=0.0, step=0.5, format="%.2f",
        disabled=not is_consigned,
        key="newp_supplier_cost",
    )

    submit = st.button("Cadastrar", type="primary", use_container_width=True)

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
        if is_consigned and not cons_opts.get(consignor_label):
            st.error("Selecione um consignante para produto consignado.")
            return

        # Verifica duplicidade de SKU
        existing = query_one("SELECT id FROM products WHERE sku = %s", [sku.strip()])
        if existing:
            st.error(f"SKU '{sku}' já está em uso.")
            return

        try:
            row = execute_returning(
                "INSERT INTO products "
                "(name, sku, price, unit_cost, stock, min_stock, is_consigned, "
                " consignor_id, supplier_unit_cost) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                [
                    name.strip(), sku.strip(), price, unit_cost or None,
                    int(stock), int(min_stock), is_consigned,
                    cons_opts.get(consignor_label) if is_consigned else None,
                    (float(supplier_cost) if (is_consigned and float(supplier_cost) > 0) else None),
                ],
            )
            pid = row["id"]

            # Registra movimento inicial se estoque > 0
            if int(stock) > 0:
                execute(
                    "INSERT INTO movements (type, product_id, qty, note, user_id) "
                    "VALUES ('IN', %s, %s, %s, %s)",
                    [pid, int(stock), "Estoque inicial", user.id],
                )

            audit_log(user, "PRODUCT_CREATE", "product", pid, {
                "name": name, "sku": sku, "price": price, "stock": stock,
            })
            st.success(f"✅ Produto #{pid} cadastrado.")
        except Exception as e:
            st.error(f"Erro: {e}")


# ---------------------------------------------------------------------------
# Edição
# ---------------------------------------------------------------------------

def _edit_form(user, product_id: int, *, can_delete: bool) -> None:
    p = query_one("SELECT * FROM products WHERE id = %s", [product_id])
    if not p:
        st.error("Produto não encontrado.")
        return

    consignors = query("SELECT id, name FROM consignors WHERE active = TRUE ORDER BY name")
    cons_opts = {"— Nenhum —": None}
    for c in consignors:
        cons_opts[c["name"]] = c["id"]
    cons_reverse = {v: k for k, v in cons_opts.items()}
    current_cons_label = cons_reverse.get(p["consignor_id"], "— Nenhum —")

    with st.form(f"edit_product_{product_id}"):
        c1, c2 = st.columns([3, 1])
        name = c1.text_input("Nome", value=p["name"])
        sku = c2.text_input("SKU", value=p["sku"])

        c3, c4 = st.columns(2)
        price = c3.number_input("Preço (R$)", min_value=0.0, value=float(p["price"]), step=0.5, format="%.2f")
        unit_cost = c4.number_input(
            "Custo unitário (R$)", min_value=0.0,
            value=float(p["unit_cost"] or 0), step=0.5, format="%.2f",
        )

        c5, c6 = st.columns(2)
        min_stock = c5.number_input("Estoque mínimo", min_value=0, value=int(p["min_stock"]), step=1)
        active = c6.checkbox("Ativo", value=bool(p["active"]))

        c7, c8 = st.columns(2)
        is_consigned = c7.checkbox("Consignado?", value=bool(p["is_consigned"]))
        consignor_label = c8.selectbox(
            "Consignante",
            list(cons_opts.keys()),
            index=list(cons_opts.keys()).index(current_cons_label),
            disabled=not is_consigned,
        )
        supplier_cost = st.number_input(
            "Repasse ao consignante (R$)",
            min_value=0.0, value=float(p["supplier_unit_cost"] or 0), step=0.5, format="%.2f",
            disabled=not is_consigned,
        )

        st.caption(f"Estoque atual: **{p['stock']}** — para alterar, use a página **Movimentações**.")

        b1, b2 = st.columns([1, 1])
        save = b1.form_submit_button("💾 Salvar alterações", type="primary", use_container_width=True)
        delete = b2.form_submit_button(
            "🗑️ Excluir produto",
            use_container_width=True,
            disabled=not can_delete,
            help="Apenas admin pode excluir." if not can_delete else None,
        )

    if save:
        execute(
            "UPDATE products SET name=%s, sku=%s, price=%s, unit_cost=%s, "
            "min_stock=%s, active=%s, is_consigned=%s, consignor_id=%s, "
            "supplier_unit_cost=%s WHERE id=%s",
            [
                name.strip(), sku.strip(), price, unit_cost or None,
                int(min_stock), active, is_consigned,
                cons_opts.get(consignor_label) if is_consigned else None,
                supplier_cost or None if is_consigned else None,
                product_id,
            ],
        )
        audit_log(user, "PRODUCT_UPDATE", "product", product_id, {
            "name": name, "sku": sku, "price": price, "active": active,
        })
        st.success("✅ Alterações salvas.")
        st.rerun()

    if delete and can_delete:
        # Checa FK: se tem venda ou movimento, não exclui — marca como inativo
        has_sales = query_one(
            "SELECT 1 FROM sale_items WHERE product_id = %s LIMIT 1", [product_id],
        )
        if has_sales:
            st.warning(
                "Produto tem histórico de vendas e não pode ser excluído. "
                "Marcado como **inativo**."
            )
            execute("UPDATE products SET active = FALSE WHERE id = %s", [product_id])
            audit_log(user, "PRODUCT_DEACTIVATE", "product", product_id)
        else:
            with get_conn() as conn:
                conn.execute("DELETE FROM movements WHERE product_id = %s", [product_id])
                conn.execute("DELETE FROM products WHERE id = %s", [product_id])
                conn.commit()
            audit_log(user, "PRODUCT_DELETE", "product", product_id, {"name": p["name"]})
            st.success("🗑️ Produto excluído.")
        st.rerun()
