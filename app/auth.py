"""Módulo de autenticación simple para la aplicación Streamlit de Comparador de Normativas.

La lógica de credenciales vive en `app/auth_core.py` y se comparte con la API FastAPI
(`api/security.py`); aquí queda solo lo que depende de Streamlit.
"""
from __future__ import annotations

import streamlit as st

from app.auth_core import (
    DEFAULT_USERNAME,
    credentials_are_configured,
    get_configured_credentials,
    is_auth_enabled,
    verify_credentials,
)

__all__ = [
    "DEFAULT_USERNAME",
    "check_auth",
    "credentials_are_configured",
    "get_configured_credentials",
    "is_auth_enabled",
    "render_user_sidebar",
    "verify_credentials",
]


def check_auth() -> bool:
    """Verifica si el usuario está autenticado. Si no, renderiza el formulario de login.

    Retorna True si la sesión está autenticada (o si la autenticación está deshabilitada),
    o False si no lo está (en cuyo caso se debe detener la ejecución de la app con st.stop()).
    """
    if not is_auth_enabled():
        return True

    if st.session_state.get("authenticated", False):
        return True

    # Renderiza tarjeta de login limpia y centrada
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### 🔐 Acceso al Sistema")
        st.markdown(
            "Ingrese sus credenciales autorizadas para acceder al **Comparador de Normativas vs Manuales**."
        )

        with st.form("login_form", clear_on_submit=False):
            username_input = st.text_input("Usuario", key="login_username")
            password_input = st.text_input(
                "Contraseña", type="password", key="login_password"
            )
            submit_btn = st.form_submit_button("Iniciar sesión", use_container_width=True)

            if submit_btn:
                if verify_credentials(username_input, password_input):
                    st.session_state["authenticated"] = True
                    st.session_state["auth_user"] = username_input
                    st.success("Acceso concedido. Redirigiendo...")
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas. Verifique usuario y contraseña.")

    return False


def render_user_sidebar() -> None:
    """Muestra información del usuario autenticado en la barra lateral con opción de salir."""
    if not is_auth_enabled():
        return

    current_user = st.session_state.get("auth_user", DEFAULT_USERNAME)
    st.sidebar.markdown(f"**Usuario:** `{current_user}`")
    if st.sidebar.button("Cerrar sesión", key="btn_logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.session_state.pop("auth_user", None)
        st.rerun()
    st.sidebar.markdown("---")
