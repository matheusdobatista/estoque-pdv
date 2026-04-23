"""
Autenticação e autorização.

Estratégia:
- Hash de senha com bcrypt (rounds=12).
- Sessão mantida em st.session_state (isolada por browser tab no Streamlit).
- Papéis: ADMIN, OPERADOR, GERENCIAL — ver schema.sql.
- Guarda `require_login()` no topo de cada página; `require_role()` onde precisar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import bcrypt
import streamlit as st

from db import query_one, execute


# ---------------------------------------------------------------------------
# Modelo de usuário em sessão
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    full_name: str
    role: str  # 'ADMIN' | 'OPERADOR' | 'GERENCIAL'


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Retorna hash bcrypt (str) pronto pra guardar no banco."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

def _set_session_user(user: CurrentUser) -> None:
    st.session_state["current_user"] = user


def current_user() -> CurrentUser | None:
    return st.session_state.get("current_user")


def is_logged_in() -> bool:
    return current_user() is not None


def logout() -> None:
    for key in ("current_user", "cart"):
        st.session_state.pop(key, None)


def attempt_login(username: str, password: str) -> tuple[bool, str]:
    """
    Tenta autenticar. Retorna (sucesso, mensagem).
    Registra last_login no banco quando sucesso.
    """
    username = (username or "").strip().lower()
    if not username or not password:
        return False, "Informe usuário e senha."

    row = query_one(
        "SELECT id, username, full_name, password_hash, role, active "
        "FROM users WHERE lower(username) = %s",
        [username],
    )
    if not row:
        return False, "Usuário ou senha inválidos."
    if not row["active"]:
        return False, "Usuário inativo. Procure o administrador."
    if not verify_password(password, row["password_hash"]):
        return False, "Usuário ou senha inválidos."

    execute("UPDATE users SET last_login = NOW() WHERE id = %s", [row["id"]])

    _set_session_user(CurrentUser(
        id=row["id"],
        username=row["username"],
        full_name=row["full_name"],
        role=row["role"],
    ))
    return True, "Bem-vindo!"


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def require_login() -> CurrentUser:
    """Chame no topo de qualquer página protegida."""
    user = current_user()
    if user is None:
        st.warning("Faça login para continuar.")
        st.stop()
    return user  # type: ignore


def has_role(user: CurrentUser, allowed: Iterable[str]) -> bool:
    return user.role in set(allowed)


def require_role(*allowed: str) -> CurrentUser:
    """
    Exige que o usuário tenha um dos papéis listados.
    Ex.: require_role('ADMIN', 'OPERADOR')
    """
    user = require_login()
    if not has_role(user, allowed):
        st.error("🔒 Você não tem permissão para acessar esta página.")
        st.caption(f"Seu papel: **{user.role}** — papéis permitidos: {', '.join(allowed)}")
        st.stop()
    return user


# ---------------------------------------------------------------------------
# Tela de login
# ---------------------------------------------------------------------------

def login_form() -> None:
    """Renderiza o formulário de login. Chamado quando não há usuário logado."""
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("### 🔒 Entrar no Sistema")
        st.caption("Sistema Mercadinho — VI Despertar 2026")

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Usuário", autocomplete="username")
            password = st.text_input("Senha", type="password", autocomplete="current-password")
            submit = st.form_submit_button("Entrar", use_container_width=True, type="primary")

        if submit:
            ok, msg = attempt_login(username, password)
            if ok:
                st.rerun()
            else:
                st.error(msg)

        with st.expander("Primeira vez?"):
            st.markdown(
                "Use as credenciais padrão:\n\n"
                "- **Usuário:** `admin`\n"
                "- **Senha:** `admin123`\n\n"
                "⚠️ Troque a senha após o primeiro login em **Configurações → Usuários**."
            )
