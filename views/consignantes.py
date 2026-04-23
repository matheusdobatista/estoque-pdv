"""Consignantes — CRUD."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import require_role
from db import execute, execute_returning, query, query_one


def render() -> None:
    user = require_role("ADMIN")

    st.title("🤝 Consignantes")

    tabs = st.tabs(["📋 Lista", "➕ Novo"])
    with tabs[0]:
        _tab_list(user)
    with tabs[1]:
        _tab_new(user)


def _tab_list(user) -> None:
    rows = query("""
        SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.consignor_id = c.id) AS prod_count
        FROM consignors c ORDER BY c.name
    """)
    if not rows:
        st.info("Nenhum consignante cadastrado.")
        return

    df = pd.DataFrame(rows)
    st.dataframe(
        df[["name", "phone", "pix_key", "prod_count", "active"]].rename(columns={
            "name": "Nome", "phone": "Telefone", "pix_key": "Pix",
            "prod_count": "Produtos", "active": "Ativo",
        }),
        hide_index=True, use_container_width=True,
    )

    st.divider()
    opts = {"— Selecione —": None}
    for r in rows:
        opts[r["name"]] = r["id"]
    label = st.selectbox("Editar consignante", list(opts.keys()))
    cid = opts.get(label)
    if cid:
        c = query_one("SELECT * FROM consignors WHERE id = %s", [cid])
        with st.form(f"edit_c_{cid}"):
            name = st.text_input("Nome", value=c["name"])
            phone = st.text_input("Telefone", value=c["phone"] or "")
            address = st.text_area("Endereço", value=c["address"] or "")
            pix = st.text_input("Chave Pix", value=c["pix_key"] or "")
            active = st.checkbox("Ativo", value=bool(c["active"]))
            b1, b2 = st.columns(2)
            save = b1.form_submit_button("💾 Salvar", type="primary", use_container_width=True)
            remove = b2.form_submit_button("🗑️ Excluir", use_container_width=True)

        if save:
            execute(
                "UPDATE consignors SET name=%s, phone=%s, address=%s, pix_key=%s, active=%s WHERE id=%s",
                [name.strip(), phone or None, address or None, pix or None, active, cid],
            )
            audit_log(user, "CONSIGNOR_UPDATE", "consignor", cid, {"name": name})
            st.success("Salvo.")
            st.rerun()

        if remove:
            has_prod = query_one("SELECT 1 FROM products WHERE consignor_id=%s LIMIT 1", [cid])
            if has_prod:
                execute("UPDATE consignors SET active=FALSE WHERE id=%s", [cid])
                audit_log(user, "CONSIGNOR_DEACTIVATE", "consignor", cid)
                st.warning("Consignante tem produtos vinculados — marcado como inativo.")
            else:
                execute("DELETE FROM consignors WHERE id=%s", [cid])
                audit_log(user, "CONSIGNOR_DELETE", "consignor", cid, {"name": c["name"]})
                st.success("Excluído.")
            st.rerun()


def _tab_new(user) -> None:
    with st.form("new_c", clear_on_submit=True):
        name = st.text_input("Nome*")
        phone = st.text_input("Telefone")
        address = st.text_area("Endereço")
        pix = st.text_input("Chave Pix")
        submit = st.form_submit_button("Cadastrar", type="primary", use_container_width=True)

    if submit:
        if not name.strip():
            st.error("Nome é obrigatório.")
            return
        row = execute_returning(
            "INSERT INTO consignors (name, phone, address, pix_key) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            [name.strip(), phone or None, address or None, pix or None],
        )
        audit_log(user, "CONSIGNOR_CREATE", "consignor", row["id"], {"name": name})
        st.success(f"✅ Consignante #{row['id']} cadastrado.")
