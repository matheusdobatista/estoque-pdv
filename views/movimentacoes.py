"""Movimentações de estoque — entradas, saídas, ajustes."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import has_role, require_login
from db import query, transaction
from utils import df_to_xlsx_bytes, fmt_ts


def render() -> None:
    user = require_login()
    can_write = has_role(user, {"ADMIN", "OPERADOR"})

    st.title("📈 Movimentações de Estoque")

    tabs = st.tabs(["📋 Histórico", "➕ Nova movimentação"] if can_write else ["📋 Histórico"])

    with tabs[0]:
        _tab_history(can_write, user)

    if can_write:
        with tabs[1]:
            _tab_new(user)


def _tab_history(can_write: bool, user) -> None:
    today = date.today()
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("De", value=today - timedelta(days=7))
    end = c2.date_input("Até", value=today)
    mtype = c3.selectbox("Tipo", ["Todos", "IN", "OUT", "ADJUST"])

    where = ["m.created_at >= %s", "m.created_at < %s"]
    params: list = [datetime.combine(start, datetime.min.time()),
                    datetime.combine(end + timedelta(days=1), datetime.min.time())]
    if mtype != "Todos":
        where.append("m.type = %s")
        params.append(mtype)

    rows = query(
        f"""
        SELECT m.id, m.created_at, m.type, m.qty, m.note,
               p.sku, p.name AS product_name,
               u.username
        FROM movements m
        JOIN products p ON p.id = m.product_id
        LEFT JOIN users u ON u.id = m.user_id
        WHERE {' AND '.join(where)}
        ORDER BY m.created_at DESC
        LIMIT 500
        """,
        params,
    )
    if not rows:
        st.info("Nenhuma movimentação no período.")
        return

    df = pd.DataFrame(rows)
    df["created_at"] = df["created_at"].apply(fmt_ts)
    df = df.rename(columns={
        "created_at": "Data", "type": "Tipo", "sku": "SKU",
        "product_name": "Produto", "qty": "Qtd", "note": "Observação",
        "username": "Usuário",
    })
    st.caption(f"{len(df)} movimento(s)")
    st.dataframe(
        df[["Data", "Tipo", "SKU", "Produto", "Qtd", "Observação", "Usuário"]],
        hide_index=True, use_container_width=True,
    )

    if can_write:
        st.markdown("#### 🗑️ Excluir movimentações")
        st.caption("Você pode excluir movimentações manuais (IN/OUT). Movimentos de venda (nota 'Venda #') ou ADJUST não podem ser excluídos aqui.")
        work = df.copy()
        work.insert(0, "Excluir", False)
        ed = st.data_editor(
            work[["Excluir", "Data", "Tipo", "SKU", "Produto", "Qtd", "Observação", "Usuário", "id"]],
            hide_index=True,
            use_container_width=True,
            disabled=["Data","Tipo","SKU","Produto","Qtd","Observação","Usuário","id"],
            column_config={"Excluir": st.column_config.CheckboxColumn("Excluir")},
            height=320,
            key="mov_delete_editor",
        )
        if st.button("Excluir selecionadas", type="primary", use_container_width=True):
            ids = [int(r["id"]) for _, r in ed[ed["Excluir"] == True].iterrows()]
            if not ids:
                st.warning("Selecione ao menos uma movimentação.")
            else:
                try:
                    with transaction() as conn:
                        rows = conn.execute(
                            "SELECT m.id, m.type, m.qty, m.note, m.product_id, p.stock, p.name AS product_name "
                            "FROM movements m JOIN products p ON p.id=m.product_id WHERE m.id = ANY(%s) FOR UPDATE",
                            [ids],
                        ).fetchall()
                        # validações e ajustes
                        for r in rows:
                            mtype = r["type"]
                            note = (r["note"] or "")
                            if mtype == "ADJUST":
                                raise ValueError(f"Movimento {r['id']}: tipo ADJUST não pode ser excluído.")
                            if note.strip().lower().startswith("venda #"):
                                raise ValueError(f"Movimento {r['id']}: é de venda. Exclua a venda no Dashboard.")

                        # aplica estorno de estoque e deleta
                        for r in rows:
                            pid = r["product_id"]
                            qty = int(r["qty"])
                            stock = int(r["stock"])
                            if r["type"] == "IN":
                                new_stock = stock - qty
                                if new_stock < 0:
                                    raise ValueError(f"Movimento {r['id']}: estorno deixaria estoque negativo.")
                                conn.execute("UPDATE products SET stock=%s WHERE id=%s", [new_stock, pid])
                            elif r["type"] == "OUT":
                                new_stock = stock + qty
                                conn.execute("UPDATE products SET stock=%s WHERE id=%s", [new_stock, pid])

                        conn.execute("DELETE FROM movements WHERE id = ANY(%s)", [ids])
                        audit_log(user, "MOVEMENT_DELETE", "movement", None, {"ids": ids}, conn=conn)

                    st.success(f"{len(ids)} movimentação(ões) excluída(s).")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {e}")

    st.download_button(
        "⬇️ Exportar Excel",
        data=df_to_xlsx_bytes(df, "Movimentações"),
        file_name=f"movimentacoes_{start}_{end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _tab_new(user) -> None:
    products = query("SELECT id, sku, name, stock FROM products WHERE active = TRUE ORDER BY name")
    if not products:
        st.info("Cadastre produtos antes.")
        return

    opts = {f"{p['sku']} — {p['name']} (estoque: {p['stock']})": p["id"] for p in products}

    with st.form("new_move", clear_on_submit=True):
        label = st.selectbox("Produto*", list(opts.keys()))
        c1, c2 = st.columns(2)
        mtype = c1.selectbox("Tipo*", ["IN", "OUT", "ADJUST"], help=(
            "IN = entrada  •  OUT = saída manual  •  ADJUST = ajuste absoluto do estoque"
        ))
        qty = c2.number_input("Quantidade*", min_value=1, step=1, value=1)
        note = st.text_input("Observação (opcional)")
        submit = st.form_submit_button("Registrar", type="primary", use_container_width=True)

    if submit:
        pid = opts[label]
        try:
            with transaction() as conn:
                # Lock da linha do produto
                cur = conn.execute("SELECT stock FROM products WHERE id = %s FOR UPDATE", [pid])
                row = cur.fetchone()
                if not row:
                    raise ValueError("Produto não encontrado.")
                current = row["stock"]

                if mtype == "IN":
                    new_stock = current + int(qty)
                elif mtype == "OUT":
                    if current < int(qty):
                        raise ValueError(f"Estoque insuficiente: {current} disponível, {qty} solicitado.")
                    new_stock = current - int(qty)
                else:  # ADJUST — qty é o valor absoluto final
                    new_stock = int(qty)

                conn.execute("UPDATE products SET stock = %s WHERE id = %s", [new_stock, pid])
                conn.execute(
                    "INSERT INTO movements (type, product_id, qty, note, user_id) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    [mtype, pid, int(qty), note or None, user.id],
                )
                audit_log(user, f"MOVEMENT_{mtype}", "product", pid,
                          {"qty": int(qty), "note": note, "before": current, "after": new_stock},
                          conn=conn)

            st.success(f"✅ Movimentação registrada. Novo estoque: {new_stock}")
            st.rerun()
        except Exception as e:
            st.error(f"❌ {e}")
