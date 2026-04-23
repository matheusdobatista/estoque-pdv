"""Vendedores — cadastro simples."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import require_role
from db import execute, execute_returning, query, query_one


def render() -> None:
    user = require_role("ADMIN")

    st.title("👥 Vendedores")

    tabs = st.tabs(["📋 Lista", "➕ Novo"])

    with tabs[0]:
        _tab_list(user)
    with tabs[1]:
        _tab_new(user)


def _tab_list(user) -> None:
    rows = query("""
        SELECT s.id, s.name, s.active, s.created_at,
               (SELECT COUNT(*) FROM sales WHERE seller_id = s.id) AS sales_count
        FROM sellers s
        ORDER BY s.name
    """)
    if not rows:
        st.info("Nenhum vendedor cadastrado.")
        return

    df = pd.DataFrame(rows)
    st.dataframe(
        df.rename(columns={
            "name": "Nome", "active": "Ativo",
            "created_at": "Cadastro", "sales_count": "Vendas",
        })[["Nome", "Ativo", "Vendas", "Cadastro"]],
        hide_index=True, use_container_width=True,
    )

    st.divider()
    st.subheader("Editar")
    opts = {"— Selecione —": None}
    for r in rows:
        opts[r["name"]] = r["id"]
    label = st.selectbox("Vendedor", list(opts.keys()))
    sid = opts.get(label)
    if sid:
        s = query_one("SELECT * FROM sellers WHERE id = %s", [sid])
        with st.form(f"edit_seller_{sid}"):
            new_name = st.text_input("Nome", value=s["name"])
            new_active = st.checkbox("Ativo", value=bool(s["active"]))
            c1, c2 = st.columns(2)
            save = c1.form_submit_button("💾 Salvar", type="primary", use_container_width=True)
            remove = c2.form_submit_button("🗑️ Excluir", use_container_width=True)

        if save:
            execute(
                "UPDATE sellers SET name=%s, active=%s WHERE id=%s",
                [new_name.strip(), new_active, sid],
            )
            audit_log(user, "SELLER_UPDATE", "seller", sid, {"name": new_name})
            st.success("Salvo.")
            st.rerun()

        if remove:
            has_sales = query_one("SELECT 1 FROM sales WHERE seller_id=%s LIMIT 1", [sid])
            if has_sales:
                execute("UPDATE sellers SET active=FALSE WHERE id=%s", [sid])
                audit_log(user, "SELLER_DEACTIVATE", "seller", sid)
                st.warning("Vendedor tem vendas — marcado como inativo.")
            else:
                execute("DELETE FROM sellers WHERE id=%s", [sid])
                audit_log(user, "SELLER_DELETE", "seller", sid, {"name": s["name"]})
                st.success("Excluído.")
            st.rerun()


def _tab_new(user) -> None:
    with st.form("new_seller", clear_on_submit=True):
        name = st.text_input("Nome*")
        submit = st.form_submit_button("Cadastrar", type="primary", use_container_width=True)
    if submit:
        if not name.strip():
            st.error("Nome é obrigatório.")
            return
        try:
            row = execute_returning(
                "INSERT INTO sellers (name) VALUES (%s) RETURNING id",
                [name.strip()],
            )
            audit_log(user, "SELLER_CREATE", "seller", row["id"], {"name": name})
            st.success(f"✅ Vendedor #{row['id']} cadastrado.")
        except Exception as e:
            st.error(f"Erro: {e}")
