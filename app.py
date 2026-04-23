"""
Sistema Mercadinho — Entrypoint.

Rode localmente: streamlit run app.py
Deploy: push pro GitHub → Streamlit Community Cloud conecta ao repo.
"""

from __future__ import annotations

import streamlit as st

# Configuração de página — deve ser a PRIMEIRA chamada streamlit
st.set_page_config(
    page_title="Mercadinho — VI Despertar 2026",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

from auth import current_user, is_logged_in, login_form, logout
from db import bootstrap


# ---------------------------------------------------------------------------
# CSS leve
# ---------------------------------------------------------------------------

def inject_css() -> None:
    st.markdown(
        """
        <style>
            .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px; }
            [data-testid="stSidebar"] { background: linear-gradient(180deg, #0F766E 0%, #134E4A 100%); }
            [data-testid="stSidebar"] * { color: #F0FDFA !important; }
            [data-testid="stSidebar"] .stRadio label { font-size: 0.95rem; }
            [data-testid="stSidebar"] button[kind="secondary"] {
                background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2);
            }
            div[data-testid="metric-container"] {
                background: white; padding: 1rem; border-radius: 0.75rem;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05); border: 1px solid #E2E8F0;
            }
            h1, h2, h3 { color: #0F172A; }
            .muted { color: #64748B; font-size: 0.9rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar / Router
# ---------------------------------------------------------------------------

# Mapa de páginas por papel
PAGES_BY_ROLE = {
    # Dashboard removido (será feito no Power BI)
    "ADMIN":     ["PDV", "Produtos", "Movimentações", "Fiado",
                  "Consignantes", "Vendedores", "Configurações"],
    "OPERADOR":  ["PDV", "Produtos", "Movimentações", "Fiado"],
    "GERENCIAL": ["Fiado", "Produtos", "Movimentações"],
}


def render_sidebar(user) -> str:
    st.sidebar.markdown(f"### 🛒 Mercadinho")
    st.sidebar.caption(
        st.secrets.get("app", {}).get("instance_name", "VI Despertar 2026")
    )
    st.sidebar.markdown("---")

    allowed_pages = PAGES_BY_ROLE.get(user.role, ["Dashboard"])
    page = st.sidebar.radio("Navegação", allowed_pages, label_visibility="collapsed")

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**{user.full_name}**")
    st.sidebar.caption(f"`{user.username}` • {user.role}")
    if st.sidebar.button("Sair", use_container_width=True):
        logout()
        st.rerun()

    return page


def route(page: str) -> None:
    """Despacha pra view correta."""
    if page == "PDV":
        from views import pdv; pdv.render()
    elif page == "Produtos":
        from views import produtos; produtos.render()
    elif page == "Movimentações":
        from views import movimentacoes; movimentacoes.render()
    elif page == "Fiado":
        from views import fiado; fiado.render()
    elif page == "Consignantes":
        from views import consignantes; consignantes.render()
    elif page == "Vendedores":
        from views import vendedores; vendedores.render()
    elif page == "Configurações":
        from views import config; config.render()
    else:
        st.error(f"Página desconhecida: {page}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    inject_css()

    # Garante schema no primeiro boot; falha cedo se banco estiver inacessível
    try:
        bootstrap()
    except Exception as e:
        st.error("❌ Não foi possível conectar ao banco de dados.")
        st.code(str(e))
        st.info(
            "Verifique: (1) `postgres.url` em secrets.toml; "
            "(2) banco acessível; (3) `schema.sql` sem erros."
        )
        st.stop()

    if not is_logged_in():
        login_form()
        return

    user = current_user()
    page = render_sidebar(user)
    route(page)


if __name__ == "__main__":
    main()
