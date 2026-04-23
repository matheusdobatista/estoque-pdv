"""
PDV — Ponto de Venda.

Ponto crítico: transação atômica na finalização.
Usa SELECT ... FOR UPDATE pra travar as linhas dos produtos do carrinho,
evitando que dois caixas vendam o mesmo "último item" simultaneamente.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import require_role
from db import query, transaction
from utils import BUYER_TEAMS, PAYMENT_METHODS, money_fmt


def _load_active_products() -> pd.DataFrame:
    rows = query(
        "SELECT id, name, sku, price, unit_cost, stock "
        "FROM products WHERE active = TRUE ORDER BY name"
    )
    return pd.DataFrame(rows)


def _load_active_sellers() -> list[dict]:
    return query("SELECT id, name FROM sellers WHERE active = TRUE ORDER BY name")


def render() -> None:
    user = require_role("ADMIN", "OPERADOR")

    st.title("🛒 PDV")
    st.caption("Carrinho em memória; grava no banco atomicamente ao finalizar.")

    products = _load_active_products()
    if products.empty:
        st.warning("Cadastre produtos antes de vender.")
        return

    sellers = _load_active_sellers()
    if not sellers:
        st.warning("Cadastre pelo menos um vendedor antes de vender.")
        return

    seller_opts = {"— Selecione —": None}
    for s in sellers:
        seller_opts[s["name"]] = s["id"]

    # Cart isolado por session (por aba/usuário)
    if "cart" not in st.session_state:
        st.session_state.cart = []

    # ---- Cabeçalho da venda ----
    h1, h2, h3 = st.columns([1.2, 1.4, 1.2])
    seller_name = h1.selectbox("Vendedor*", list(seller_opts.keys()))
    seller_id = seller_opts.get(seller_name)
    buyer_name = h2.text_input("Comprador (opcional)")
    buyer_team = h3.selectbox("Equipe do comprador*", BUYER_TEAMS)

    st.divider()

    # ---- Seletor de produto ----
    prod_names = products["name"].tolist()
    c1, c2, c3, c4 = st.columns([2.5, 0.8, 1.0, 1.0])
    selected_name = c1.selectbox("Produto", prod_names)
    row_p = products.loc[products["name"] == selected_name].iloc[0]
    stock_now = int(row_p["stock"])
    price_now = float(row_p["price"])

    qty = c2.number_input("Qtd", min_value=1, value=1, step=1)
    c3.number_input("Preço (R$)", value=price_now, disabled=True, format="%.2f")
    c4.number_input("Estoque atual", value=stock_now, disabled=True, step=1)

    if stock_now <= 0:
        st.error(f"Produto **{selected_name}** sem estoque.")
    elif stock_now < int(qty):
        st.warning(f"Qtd solicitada ({int(qty)}) maior que estoque ({stock_now}).")

    add_disabled = stock_now < int(qty)
    if st.button("➕ Adicionar ao carrinho", use_container_width=True, disabled=add_disabled):
        pid = int(row_p["id"])
        # Se já tem no carrinho, incrementa
        for it in st.session_state.cart:
            if it["product_id"] == pid:
                it["qty"] += int(qty)
                break
        else:
            st.session_state.cart.append({
                "product_id": pid,
                "sku": str(row_p["sku"]),
                "name": str(row_p["name"]),
                "qty": int(qty),
                "unit_price": price_now,
                "unit_cost": None if pd.isna(row_p.get("unit_cost")) else float(row_p["unit_cost"]),
            })
        st.success(f"✓ {int(qty)}× {selected_name} adicionado.")
        st.rerun()

    st.divider()

    if not st.session_state.cart:
        st.info("Carrinho vazio.")
        return

    # ---- Tabela do carrinho editável ----
    cart_df = pd.DataFrame(st.session_state.cart)
    cart_df["line_total"] = cart_df["qty"] * cart_df["unit_price"]

    edited = st.data_editor(
        cart_df[["sku", "name", "qty", "unit_price", "line_total"]],
        hide_index=True,
        disabled=["sku", "name", "unit_price", "line_total"],
        use_container_width=True,
        column_config={
            "sku": "SKU",
            "name": "Produto",
            "qty": st.column_config.NumberColumn("Qtd", min_value=1, step=1),
            "unit_price": st.column_config.NumberColumn("Preço unit.", format="R$ %.2f"),
            "line_total": st.column_config.NumberColumn("Subtotal", format="R$ %.2f"),
        },
        key="cart_editor",
    )

    # Sincroniza carrinho com edição
    new_cart = []
    for _, row in edited.iterrows():
        base = cart_df.loc[cart_df["sku"] == row["sku"]].iloc[0]
        new_cart.append({
            "product_id": int(base["product_id"]),
            "sku": str(base["sku"]),
            "name": str(base["name"]),
            "qty": int(row["qty"]),
            "unit_price": float(base["unit_price"]),
            "unit_cost": base.get("unit_cost"),
        })
    st.session_state.cart = new_cart

    total = sum(i["qty"] * i["unit_price"] for i in st.session_state.cart)
    st.markdown(f"### Total: **{money_fmt(total)}**")

    # ---- Pagamento ----
    st.divider()
        p1, p2, p3 = st.columns(3)
    payment_method = p1.selectbox("Forma de pagamento*", PAYMENT_METHODS)

    # Considera "Fiado" mesmo se o texto mudar (ex: "Fiado (em aberto)")
    is_fiado = str(payment_method).strip().lower().startswith("fiado")

    if is_fiado:
        paid = 0.0
        change = 0.0
        p2.number_input("Pago (R$)*", min_value=0.0, value=0.0, step=1.0, disabled=True)
        p3.caption("Troco")
        p3.markdown(f"**{money_fmt(change)}**")
        st.info("Venda em aberto: o estoque será baixado normalmente, e a quitação acontece depois.")
    else:
        paid = p2.number_input("Pago (R$)*", min_value=0.0, value=float(total), step=1.0)
        change = float(paid) - float(total)
        p3.caption("Troco")
        p3.markdown(f"**{money_fmt(change)}**")

    st.divider()
    f1, f2 = st.columns(2)
    finalize = f1.button("✅ Finalizar venda", type="primary", use_container_width=True)
    clear = f2.button("🗑️ Limpar carrinho", use_container_width=True)

    if clear:
        st.session_state.cart = []
        st.rerun()

    if finalize:
        if seller_id is None:
            st.error("Selecione um vendedor.")
            return
        if (not str(payment_method).strip().lower().startswith("fiado")) and float(paid) < float(total):
            st.error(f"Valor pago ({money_fmt(paid)}) menor que total ({money_fmt(total)}).")
            return
        if not st.session_state.cart:
            st.error("Carrinho vazio.")
            return

        try:
            sale_id = _finalize_sale(
                user=user,
                cart=st.session_state.cart,
                seller_id=int(seller_id),
                buyer_name=buyer_name.strip() or None,
                buyer_team=buyer_team,
                payment_method=payment_method,
                total=float(total),
                paid=float(paid) if payment_method != "Fiado" else 0.0,
                change=float(change) if payment_method != "Fiado" else 0.0,
            )
        except InsufficientStockError as e:
            st.error(f"❌ Estoque insuficiente: {e}")
            return
        except Exception as e:
            st.error(f"❌ Erro ao finalizar venda: {e}")
            return

        st.session_state.cart = []
        st.success(f"✅ Venda #{sale_id} finalizada! Total: {money_fmt(total)}")
        st.balloons()
        st.rerun()


# ---------------------------------------------------------------------------
# Transação atômica
# ---------------------------------------------------------------------------

class InsufficientStockError(Exception):
    pass


def _finalize_sale(
    *,
    user,
    cart: list[dict],
    seller_id: int,
    buyer_name: str | None,
    buyer_team: str,
    payment_method: str,
    total: float,
    paid: float,
    change: float,
) -> int:
    """
    Executa a venda dentro de UMA transação.
    Passos:
      1) SELECT ... FOR UPDATE nas linhas de products envolvidas (trava as linhas)
      2) Re-valida estoque (pode ter mudado entre carregar tela e finalizar)
      3) INSERT sale, INSERT sale_items (um por item), INSERT movements, UPDATE products
      4) audit_log
      5) commit
    Rollback automático em qualquer exceção.
    """
    product_ids = [it["product_id"] for it in cart]
    is_fiado = str(payment_method).strip().lower().startswith("fiado")
    status = "ABERTO" if is_fiado else "PAGO"

    with transaction() as conn:
        # 1+2) Lock + re-validação
        cur = conn.execute(
            "SELECT id, name, stock FROM products WHERE id = ANY(%s) FOR UPDATE",
            [product_ids],
        )
        stock_by_id = {r["id"]: (r["name"], r["stock"]) for r in cur.fetchall()}
        for it in cart:
            name, have = stock_by_id.get(it["product_id"], (None, 0))
            if name is None:
                raise InsufficientStockError(f"Produto {it['sku']} não encontrado.")
            if have < it["qty"]:
                raise InsufficientStockError(
                    f"{name}: disponível {have}, solicitado {it['qty']}"
                )

        # 3) Sale
        cur = conn.execute(
            "INSERT INTO sales "
            "(seller_id, buyer_name, buyer_team, payment_method, payment_status, "
            " total, paid, change_amount, user_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            [seller_id, buyer_name, buyer_team, payment_method, status,
             total, paid, change, user.id],
        )
        sale_id = cur.fetchone()["id"]

        # 3) Items + movements + stock decrement (em massa via executemany poderia, mas
        # aqui fazemos um loop simples; volume é pequeno)
        for it in cart:
            line_total = round(it["qty"] * it["unit_price"], 2)
            conn.execute(
                "INSERT INTO sale_items "
                "(sale_id, product_id, qty, unit_price, unit_cost, line_total) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                [sale_id, it["product_id"], it["qty"], it["unit_price"],
                 it["unit_cost"], line_total],
            )
            conn.execute(
                "INSERT INTO movements (type, product_id, qty, note, user_id) "
                "VALUES ('OUT', %s, %s, %s, %s)",
                [it["product_id"], it["qty"], f"Venda #{sale_id}", user.id],
            )
            conn.execute(
                "UPDATE products SET stock = stock - %s WHERE id = %s",
                [it["qty"], it["product_id"]],
            )

        # 4) Audit
        audit_log(
            user=user,
            action="SALE_CREATE",
            entity="sale",
            entity_id=sale_id,
            details={
                "total": total, "payment_method": payment_method,
                "status": status, "items": len(cart), "buyer_team": buyer_team,
            },
            conn=conn,
        )

    return sale_id
