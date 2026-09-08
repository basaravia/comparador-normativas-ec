"""Módulo de autenticación simple para la aplicación Streamlit de Comparador de Normativas.
"""
from __future__ import annotations

import hmac

import streamlit as st

from src.settings import get as get_setting

DEFAULT_USERNAME = "asaravia002"


def is_auth_enabled() -> bool:
    """Indica si la autenticación está activa. Por defecto True.

    Vía `src.settings.get()`, no `os.getenv()` directo: este módulo se importa antes
    de que nada más en la app cargue `.env` (`streamlit_app.py` llama a `check_auth()`
    en el arranque), así que un `AUTH_ENABLED`/`AUTH_PASSWORD` puesto solo en `.env`
    —la convención documentada del proyecto— se leía como si no existiera. `get()`
    llama a `cargar_env()` internamente antes de mirar el entorno.
    """
    return get_setting("AUTH_ENABLED", default="true", cast=bool)


def get_configured_credentials() -> tuple[str, str]:
    """Retorna el usuario y contraseña configurados vía variables de entorno o defaults."""
    user = get_setting("AUTH_USERNAME", default=DEFAULT_USERNAME)
    pwd = get_setting("AUTH_PASSWORD", default="")
    return user, pwd


def verify_credentials(username: str, password: str) -> bool:
    """Verificación segura en tiempo constante de credenciales."""
    expected_user, expected_pwd = get_configured_credentials()
    user_match = hmac.compare_digest(username.encode("utf-8"), expected_user.encode("utf-8"))
    pwd_match = hmac.compare_digest(password.encode("utf-8"), expected_pwd.encode("utf-8"))
    return user_match and pwd_match


def check_auth() -> bool:
    """Verifica si el usuario está autenticado. Si no, renderiza el formulario de login.

    Retorna True si la sesión está autenticada (o si la autenticación está deshabilitada),
    o False si no lo está (en cuyo caso se debe detener la ejecución de la app con st.stop()).
    """
    if not is_auth_enabled():
        return True

    if st.session_state.get("authenticated", False):
        return True

    _, expected_pwd = get_configured_credentials()
    if not expected_pwd:
        # Fail-closed: AUTH_ENABLED=true sin AUTH_PASSWORD configurada dejaba entrar
        # con cualquier usuario y contraseña vacía (hmac.compare_digest("", "") es
        # True). No hay contraseña por defecto segura que inventar aquí — se detiene
        # la app y se dice exactamente qué falta, en vez de abrir el acceso.
        st.error(
            "🔒 Autenticación habilitada pero `AUTH_PASSWORD` no está configurada. "
            "La app no puede arrancar así — defínela en `.env` o desactiva la "
            "autenticación con `AUTH_ENABLED=false` si es un entorno de prueba local."
        )
        st.stop()

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
