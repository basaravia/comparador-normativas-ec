"""Router de autenticación: login, logout y verificación de sesión.

Emite y revoca la cookie firmada `auth_session` descrita en `api/security.py`.
Es el único router público de la API (junto con salud y tokens de diseño): todo
lo demás cuelga de `require_session`.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from api.schemas import LoginRequest, LoginResponse, LogoutResponse, SessionResponse
from api.security import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    cookie_debe_ser_segura,
    credentials_are_configured,
    crear_token_sesion,
    is_auth_enabled,
    obtener_sesion,
    require_session,
    verify_credentials,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, response: Response) -> LoginResponse:
    """Valida credenciales y emite la cookie de sesión firmada `auth_session`."""
    if not is_auth_enabled():
        return LoginResponse(ok=True, usuario=payload.username, expira_en=SESSION_TTL_SECONDS)

    if not credentials_are_configured():
        # Mejor un 503 ruidoso que un despliegue que acepta cualquier contraseña vacía.
        logger.error("Intento de login con AUTH_USERNAME/AUTH_PASSWORD sin configurar en .env")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenticación no configurada en el servidor (defina AUTH_USERNAME y AUTH_PASSWORD).",
        )

    if not verify_credentials(payload.username, payload.password):
        logger.warning("Login fallido para el usuario '%s' desde %s", payload.username, request.client.host if request.client else "?")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas. Verifique usuario y contraseña.",
        )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=crear_token_sesion(payload.username),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=cookie_debe_ser_segura(request),
        path="/",
    )
    logger.info("Sesión iniciada para el usuario '%s'", payload.username)
    return LoginResponse(ok=True, usuario=payload.username, expira_en=SESSION_TTL_SECONDS)


@router.post("/logout", response_model=LogoutResponse)
def logout(request: Request, response: Response) -> LogoutResponse:
    """Borra la cookie de sesión. Idempotente: sirve aunque no hubiera sesión."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=cookie_debe_ser_segura(request),
    )
    return LogoutResponse(ok=True)


@router.get("/me", response_model=SessionResponse)
def me(sesion: dict = Depends(require_session)) -> SessionResponse:
    """Valida la sesión activa y retorna el usuario autenticado (401 si no la hay)."""
    return SessionResponse(
        autenticado=True,
        usuario=sesion.get("sub", ""),
        expira_en=sesion.get("exp"),
        auth_habilitada=is_auth_enabled(),
    )


@router.get("/status", response_model=SessionResponse)
def status_sesion(request: Request) -> SessionResponse:
    """Estado de sesión sin fallar con 401.

    La SPA lo consulta al arrancar para decidir si pinta el login o la app: un 401
    en la consola del navegador en cada carga inicial es ruido, no información.
    """
    sesion = obtener_sesion(request)
    return SessionResponse(
        autenticado=sesion is not None,
        usuario=(sesion or {}).get("sub", ""),
        expira_en=(sesion or {}).get("exp"),
        auth_habilitada=is_auth_enabled(),
    )
