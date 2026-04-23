"""Configurações — gestão de usuários, visualização de audit log."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from audit import log as audit_log
from auth import hash_password, require_role, verify_password
from db import execute, execute_returning, query, query_one
from utils import ROLE_LABELS, fmt_ts


def render() -> None:
    user = require_role("ADMIN")

    st.title("⚙️ Configurações")

    tabs = st.tabs(["👤 Meu perfil", "👥 Usuários", "➕ Novo usuário", "📜 Auditoria"])

    with tabs[0]:
        _tab_my_profile(user)
    with tabs[1]:
        _tab_users(user)
    with tabs[2]:
        _tab_new_user(user)
    with tabs[3]:
        _tab_audit()


# ---------------------------------------------------------------------------
# Meu perfil
# ---------------------------------------------------------------------------

def _tab_my_profile(user) -> None:
    st.subheader("Trocar minha senha")
    with st.form("change_password"):
        old = st.text_input("Senha atual", type="password")
        new = st.text_input("Nova senha", type="password")
        new2 = st.text_input("Repita a nova senha", type="password")
        submit = st.form_submit_button("💾 Alterar senha", type="primary")

    if submit:
        if not new or new != new2:
            st.error("Nova senha e confirmação não batem.")
            return
        if len(new) < 6:
            st.error("Senha deve ter pelo menos 6 caracteres.")
            return
        row = query_one("SELECT password_hash FROM users WHERE id = %s", [user.id])
        if not verify_password(old, row["password_hash"]):
            st.error("Senha atual incorreta.")
            return
        execute("UPDATE users SET password_hash = %s WHERE id = %s", [hash_password(new), user.id])
        audit_log(user, "PASSWORD_CHANGE", "user", user.id)
        st.success("✅ Senha alterada.")


# ---------------------------------------------------------------------------
# Lista de usuários + edição
# ---------------------------------------------------------------------------

def _tab_users(user) -> None:
    rows = query("""
        SELECT id, username, full_name, email, role, active, created_at, last_login
        FROM users ORDER BY full_name
    """)
    df = pd.DataFrame(rows)
    if not df.empty:
        df_display = df.copy()
        df_display["created_at"] = df_display["created_at"].apply(fmt_ts)
        df_display["last_login"] = df_display["last_login"].apply(fmt_ts)
        df_display["role"] = df_display["role"].map(lambda r: ROLE_LABELS.get(r, r))
        st.dataframe(
            df_display[["username", "full_name", "email", "role", "active", "last_login"]].rename(columns={
                "username": "Usuário", "full_name": "Nome", "email": "Email",
                "role": "Papel", "active": "Ativo", "last_login": "Último login",
            }),
            hide_index=True, use_container_width=True,
        )

    st.divider()
    st.subheader("Editar usuário")
    opts = {"— Selecione —": None}
    for _, r in df.iterrows():
        opts[f"{r['username']} — {r['full_name']}"] = int(r["id"])
    label = st.selectbox("Usuário", list(opts.keys()))
    uid = opts.get(label)
    if uid:
        _edit_user(user, uid)


def _edit_user(current_user, uid: int) -> None:
    u = query_one("SELECT * FROM users WHERE id = %s", [uid])
    if not u:
        st.error("Usuário não encontrado.")
        return

    is_self = (current_user.id == uid)

    with st.form(f"edit_user_{uid}"):
        c1, c2 = st.columns(2)
        full_name = c1.text_input("Nome completo", value=u["full_name"])
        email = c2.text_input("Email", value=u["email"] or "")

        c3, c4 = st.columns(2)
        role_keys = list(ROLE_LABELS.keys())
        role = c3.selectbox(
            "Papel",
            role_keys,
            index=role_keys.index(u["role"]),
            disabled=is_self,
            help="Você não pode alterar o próprio papel." if is_self else None,
        )
        active = c4.checkbox("Ativo", value=bool(u["active"]), disabled=is_self)

        st.caption("Deixe em branco pra manter a senha atual.")
        new_pass = st.text_input("Nova senha (opcional)", type="password")

        b1, b2 = st.columns(2)
        save = b1.form_submit_button("💾 Salvar", type="primary", use_container_width=True)
        remove = b2.form_submit_button(
            "🗑️ Desativar", use_container_width=True, disabled=is_self,
        )

    if save:
        if new_pass and len(new_pass) < 6:
            st.error("Senha deve ter pelo menos 6 caracteres.")
            return

        sets = ["full_name=%s", "email=%s", "role=%s", "active=%s"]
        params: list = [full_name.strip(), email.strip() or None, role, active]

        if new_pass:
            sets.append("password_hash=%s")
            params.append(hash_password(new_pass))

        params.append(uid)
        execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s", params)
        audit_log(current_user, "USER_UPDATE", "user", uid, {
            "role": role, "active": active, "password_changed": bool(new_pass),
        })
        st.success("✅ Usuário atualizado.")
        st.rerun()

    if remove and not is_self:
        execute("UPDATE users SET active = FALSE WHERE id=%s", [uid])
        audit_log(current_user, "USER_DEACTIVATE", "user", uid)
        st.success("Usuário desativado.")
        st.rerun()


# ---------------------------------------------------------------------------
# Novo usuário
# ---------------------------------------------------------------------------

def _tab_new_user(user) -> None:
    with st.form("new_user", clear_on_submit=True):
        c1, c2 = st.columns(2)
        username = c1.text_input("Usuário (login)*")
        full_name = c2.text_input("Nome completo*")
        c3, c4 = st.columns(2)
        email = c3.text_input("Email")
        role_keys = list(ROLE_LABELS.keys())
        role = c4.selectbox("Papel*", role_keys, index=role_keys.index("OPERADOR"))
        password = st.text_input("Senha inicial*", type="password")
        submit = st.form_submit_button("Cadastrar", type="primary", use_container_width=True)

    if submit:
        if not username.strip() or not full_name.strip() or not password:
            st.error("Preencha usuário, nome e senha.")
            return
        if len(password) < 6:
            st.error("Senha deve ter pelo menos 6 caracteres.")
            return

        uname = username.strip().lower()
        if query_one("SELECT 1 FROM users WHERE lower(username) = %s", [uname]):
            st.error(f"Usuário '{uname}' já existe.")
            return

        try:
            row = execute_returning(
                "INSERT INTO users (username, full_name, email, password_hash, role) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                [uname, full_name.strip(), email.strip() or None, hash_password(password), role],
            )
            audit_log(user, "USER_CREATE", "user", row["id"], {
                "username": uname, "role": role,
            })
            st.success(f"✅ Usuário '{uname}' criado.")
        except Exception as e:
            st.error(f"Erro: {e}")


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------

def _tab_audit() -> None:
    rows = query("""
        SELECT created_at, username, action, entity, entity_id, details
        FROM audit_log
        ORDER BY created_at DESC
        LIMIT 300
    """)
    if not rows:
        st.info("Sem registros ainda.")
        return
    df = pd.DataFrame(rows)
    df["created_at"] = df["created_at"].apply(fmt_ts)
    df["details"] = df["details"].apply(lambda d: str(d) if d else "")
    df = df.rename(columns={
        "created_at": "Quando", "username": "Usuário", "action": "Ação",
        "entity": "Entidade", "entity_id": "ID", "details": "Detalhes",
    })
    st.caption(f"Últimas {len(df)} ações")
    st.dataframe(df, hide_index=True, use_container_width=True)
