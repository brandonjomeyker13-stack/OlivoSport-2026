"""Sesiones: emisión, rotación y revocación de refresh tokens.

Es la parte más delicada del auth: si la rotación se rompe, o el reuso
de un token viejo deja de disparar la revocación en cascada, un token
robado sirve para siempre y nadie se entera.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.repositories import refresh_token_repository
from app.services import auth_service, user_service


def test_issue_tokens_guarda_el_refresh_hasheado_nunca_en_claro(db, usuario):
    _, raw_refresh, _ = auth_service.issue_tokens(db, user_id=usuario.id)

    guardado = refresh_token_repository.get_by_raw_token(db, raw_refresh)
    assert guardado is not None
    assert guardado.token_hash != raw_refresh
    assert len(guardado.token_hash) == 64
    assert guardado.revoked_at is None


def test_rotar_revoca_el_anterior_y_lo_encadena_al_nuevo(db, usuario):
    _, raw_viejo, _ = auth_service.issue_tokens(db, user_id=usuario.id)

    _, raw_nuevo, _ = auth_service.rotate_refresh_token(db, raw_viejo)

    assert raw_nuevo != raw_viejo
    viejo = refresh_token_repository.get_by_raw_token(db, raw_viejo)
    nuevo = refresh_token_repository.get_by_raw_token(db, raw_nuevo)
    assert viejo.revoked_at is not None
    assert viejo.replaced_by_id == nuevo.id
    assert nuevo.revoked_at is None


def test_reusar_un_refresh_ya_rotado_cierra_TODAS_las_sesiones(db, usuario):
    """Señal clásica de token robado: se cierra la sesión en todos los
    dispositivos, no solo en el que reusó el token."""
    _, raw_celular, _ = auth_service.issue_tokens(db, user_id=usuario.id)
    _, raw_computador, _ = auth_service.issue_tokens(db, user_id=usuario.id)
    _, raw_celular_rotado, _ = auth_service.rotate_refresh_token(db, raw_celular)

    with pytest.raises(auth_service.InvalidRefreshTokenError):
        auth_service.rotate_refresh_token(db, raw_celular)

    for raw in (raw_celular, raw_celular_rotado, raw_computador):
        assert refresh_token_repository.get_by_raw_token(db, raw).revoked_at is not None


def test_refresh_expirado_es_rechazado(db, usuario):
    _, raw_refresh, _ = auth_service.issue_tokens(db, user_id=usuario.id)
    fila = refresh_token_repository.get_by_raw_token(db, raw_refresh)
    fila.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    with pytest.raises(auth_service.InvalidRefreshTokenError):
        auth_service.rotate_refresh_token(db, raw_refresh)


def test_refresh_desconocido_es_rechazado(db):
    with pytest.raises(auth_service.InvalidRefreshTokenError):
        auth_service.rotate_refresh_token(db, "token-que-nunca-existio")


def test_logout_es_idempotente(db, usuario):
    _, raw_refresh, _ = auth_service.issue_tokens(db, user_id=usuario.id)

    auth_service.revoke_refresh_token(db, raw_refresh)
    revocado_en = refresh_token_repository.get_by_raw_token(db, raw_refresh).revoked_at

    # Segundo logout con la misma cookie: no explota ni pisa la fecha.
    auth_service.revoke_refresh_token(db, raw_refresh)
    auth_service.revoke_refresh_token(db, "token-que-nunca-existio")
    assert refresh_token_repository.get_by_raw_token(db, raw_refresh).revoked_at == revocado_en


def test_usuario_creado_con_google_no_puede_entrar_con_contrasena(db, crear_usuario):
    """Un usuario sin password_hash no debe poder loguearse por más que
    mande cualquier contraseña (incluida una vacía)."""
    crear_usuario(email="google@pruebas.olivosport.co", password=None)

    for intento in ("", "password-de-prueba", "cualquier-cosa"):
        with pytest.raises(user_service.InvalidCredentialsError):
            user_service.authenticate(db, email="google@pruebas.olivosport.co", password=intento)


def test_usuario_inactivo_no_puede_loguearse(db, crear_usuario):
    crear_usuario(email="inactivo@pruebas.olivosport.co", password="password-de-prueba", is_active=False)

    with pytest.raises(user_service.InvalidCredentialsError):
        user_service.authenticate(
            db, email="inactivo@pruebas.olivosport.co", password="password-de-prueba"
        )


# --- Flujo completo por HTTP ---------------------------------------------


def test_login_deja_el_refresh_en_una_cookie_httponly_y_no_en_el_body(client, usuario):
    respuesta = client.post(
        "/api/v1/auth/login",
        data={"username": usuario.email, "password": "password-de-prueba"},
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["token_type"] == "bearer"
    assert "refresh" not in respuesta.text.lower()

    set_cookie = respuesta.headers["set-cookie"]
    assert settings.REFRESH_TOKEN_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie


def test_refresh_por_http_entrega_un_access_token_nuevo(client, usuario):
    client.post(
        "/api/v1/auth/login",
        data={"username": usuario.email, "password": "password-de-prueba"},
    )

    respuesta = client.post("/api/v1/auth/refresh")

    assert respuesta.status_code == 200
    assert respuesta.json()["access_token"]


def test_refresh_sin_cookie_devuelve_401(client):
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_me_exige_token_valido(client, usuario):
    assert client.get("/api/v1/auth/me").status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        data={"username": usuario.email, "password": "password-de-prueba"},
    )
    access_token = login.json()["access_token"]

    respuesta = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["email"] == usuario.email
