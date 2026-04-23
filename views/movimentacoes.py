"""Movimentações de estoque — entradas, saídas, ajustes.

Inclui exclusão de movimentações.

Regra de consistência:
- Se a movimentação estiver vinculada a uma venda (nota "Venda #<id>"),
  ao excluir a movimentação nós excluímos a VENDA inteira (e estornamos estoque)
  para manter tudo consistente (itens + faturamento + estoque).
- Para movimentações manuais (IN/OUT/ADJUST), exclui e ajusta estoque.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import re

import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import has_role, require_login
from db import query, transaction
from utils import df_to_xlsx_bytes, fmt_ts


_RE_SALE = re.compile(r"\bVenda\s*#\s*(\d+)\b", re.IGNORECASE)


def render() -> None:
    user = require_login()
    can_write = has_role(user, {"ADMIN", "OPERADOR"})

    st.title("📈 Movimentações de Estoque")

    tabs = st.tabs(["📋 Histórico", "➕ Nova movimentação"] if can_write else ["📋 Histórico"])

    with tabs[0]:
        _tab_history()

    if can_write:
        with tabs[1]:
            _tab_new(user)


def _tab_history() -> None:
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
        SELECT m.id, m.product_id, m.created_at, m.type, m.qty, m.note,
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
        "id": "ID",
        "created_at": "Data",
        "type": "Tipo",
        "sku": "SKU",
        "product_name": "Produto",
        "qty": "Qtd",
        "note": "Observação",
        "username": "Usuário",
        "product_id": "PRODUCT_ID",
    })
    st.caption(f"{len(df)} movimento(s)")

    st.markdown("#### 🗑️ Excluir movimentações")
    st.caption(
        "Selecione e exclua. Se a movimentação estiver vinculada a uma venda (nota 'Venda #'), "
        "o sistema excluirá a venda inteira para manter consistência (estoque + itens + faturamento)."
    )

    # Data editor com seleção
    work = df.copy()
    work["Excluir"] = False
    editor = st.data_editor(
        work[["Excluir", "ID", "Data", "Tipo", "SKU", "Produto", "Qtd", "Observação", "Usuário"]],
        hide_index=True,
        use_container_width=True,
        disabled=["ID", "Data", "Tipo", "SKU", "Produto", "Qtd", "Observação", "Usuário"],
        column_config={
            "Excluir": st.column_config.CheckboxColumn("Excluir"),
        },
        height=420,
    )

    if st.button("🗑️ Excluir selecionadas", type="primary", use_container_width=True):
        to_del = editor[editor["Excluir"] == True]
        if to_del.empty:
            st.warning("Selecione ao menos uma movimentação.")
        else:
            _delete_movements(df, to_del)
            st.success("Exclusão concluída.")
            st.rerun()

    st.download_button(
        "⬇️ Exportar Excel",
        data=df_to_xlsx_bytes(df[["Data", "Tipo", "SKU", "Produto", "Qtd", "Observação", "Usuário"]], "Movimentações"),
        file_name=f"movimentacoes_{start}_{end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _delete_movements(df_all: pd.DataFrame, df_sel: pd.DataFrame) -> None:
    """Exclui movimentos selecionados.

    - Movimentos de venda: exclui venda inteira.
    - Movimentos manuais: exclui movimento e ajusta estoque.
    """
    # Determinar sale_ids a partir da observação
    sale_ids: set[int] = set()
    manual_rows: list[dict] = []

    for _, r in df_sel.iterrows():
        note = str(r.get("Observação") or "")
        m = _RE_SALE.search(note)
        if m:
            try:
                sale_ids.add(int(m.group(1)))
                continue
            except Exception:
                pass
        manual_rows.append({
            "movement_id": int(r["ID"]),
            "product_id": int(df_all.loc[df_all["ID"] == int(r["ID"]), "PRODUCT_ID"].iloc[0]),
            "type": str(r.get("Tipo") or ""),
            "qty": int(r.get("Qtd") or 0),
        })

    with transaction() as conn:
        # 1) Excluir vendas (estorno)
        for sid in sorted(sale_ids):
            _delete_sale(conn, sid)

        # 2) Excluir movimentos manuais e ajustar estoque
        if manual_rows:
            pids = sorted({x["product_id"] for x in manual_rows})
            conn.execute("SELECT id FROM products WHERE id = ANY(%s) FOR UPDATE", [pids])

        for mr in manual_rows:
            pid = mr["product_id"]
            qty = mr["qty"]
            mtype = mr["type"]
            if qty <= 0:
                continue
            if mtype == "IN":
                conn.execute("UPDATE products SET stock = stock - %s WHERE id = %s", [qty, pid])
            elif mtype == "OUT":
                conn.execute("UPDATE products SET stock = stock + %s WHERE id = %s", [qty, pid])
            elif mtype == "ADJUST":
                # Não invertível sem histórico de estoque; mantém estoque atual.
                pass
            conn.execute("DELETE FROM movements WHERE id = %s", [mr["movement_id"]])


def _delete_sale(conn, sale_id: int) -> None:
    """Exclui venda e estorna estoque (itens + movimentos)."""
    items = conn.execute(
        "SELECT product_id, qty FROM sale_items WHERE sale_id = %s",
        [sale_id],
    ).fetchall()

    if items:
        pids = sorted({int(i["product_id"]) for i in items})
        conn.execute("SELECT id FROM products WHERE id = ANY(%s) FOR UPDATE", [pids])
        for it in items:
            conn.execute(
                "UPDATE products SET stock = stock + %s WHERE id = %s",
                [int(it["qty"]), int(it["product_id"])],
            )

    # Apagar movimentos vinculados e a venda
    conn.execute("DELETE FROM movements WHERE note ILIKE %s", [f"Venda #{sale_id}%"])
    conn.execute("DELETE FROM sales WHERE id = %s", [sale_id])


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
