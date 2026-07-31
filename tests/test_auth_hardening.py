"""Protecciones alrededor del login: CSRF por Origin, IP real detrás del
proxy para el rate limit, y reglas de la contraseña."""

import pytest
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.requests import Request

from app.core.limiter import client_ip
from app.schemas.user import SetPasswordRequest, UserCreate


def _request_con_headers(headers: dict) -> Request:
    return Request(
        {
            "type": "http",
            "headers": Headers(headers).raw,
            "client": ("10.0.0.5", 1234),
        }
    )


# --- CSRF: la cookie del refresh viaja cross-site (SameSite=None) -------


def login(client, email: str, password: str) -> None:
    client.post("/api/v1/auth/login", data={"username": email, "password": password})


def test_refresh_desde_un_sitio_ajeno_es_rechazado(client, crear_usuario):
    usuario = crear_usuario(email="cliente@pruebas.olivosport.co", password="Clave-Segura-123")
    login(client, usuario.email, "Clave-Segura-123")

    respuesta = client.post(
        "/api/v1/auth/refresh", headers={"Origin": "https://sitio-malicioso.com"}
    )

    assert respuesta.status_code == 403
    # Y la sesión sigue viva: el intento no rotó ni revocó nada.
    assert client.post("/api/v1/auth/refresh").status_code == 200


def test_logout_desde_un_sitio_ajeno_no_cierra_la_sesion(client, crear_usuario):
    usuario = crear_usuario(email="cliente2@pruebas.olivosport.co", password="Clave-Segura-123")
    login(client, usuario.email, "Clave-Segura-123")

    respuesta = client.post(
        "/api/v1/auth/logout", headers={"Origin": "https://sitio-malicioso.com"}
    )

    assert respuesta.status_code == 403
    assert client.post("/api/v1/auth/refresh").status_code == 200


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "https://olivo-sport.lovable.app"],
)
def test_el_frontend_de_verdad_si_puede_refrescar(client, crear_usuario, origin):
    usuario = crear_usuario(email=f"ok{hash(origin)}@pruebas.olivosport.co", password="Clave-1234")
    login(client, usuario.email, "Clave-1234")

    respuesta = client.post("/api/v1/auth/refresh", headers={"Origin": origin})

    assert respuesta.status_code == 200
    assert respuesta.json()["access_token"]


# --- Rate limit: quién es el cliente detrás del proxy -------------------


def test_sin_proxy_se_usa_la_ip_de_la_conexion(monkeypatch):
    monkeypatch.setattr("app.core.limiter.settings.TRUSTED_PROXY_HOPS", 0)
    request = _request_con_headers({"x-forwarded-for": "1.2.3.4"})

    # El header se ignora: sin proxy declarado, es dato del cliente.
    assert client_ip(request) == "10.0.0.5"


def test_con_un_proxy_se_usa_lo_que_el_proxy_agrego(monkeypatch):
    monkeypatch.setattr("app.core.limiter.settings.TRUSTED_PROXY_HOPS", 1)
    request = _request_con_headers({"x-forwarded-for": "203.0.113.9"})

    assert client_ip(request) == "203.0.113.9"


def test_no_se_puede_esquivar_el_limite_falsificando_la_cadena(monkeypatch):
    """Si el atacante manda su propio X-Forwarded-For, el proxy le agrega
    su IP real al final; contando desde la derecha, se lee esa."""
    monkeypatch.setattr("app.core.limiter.settings.TRUSTED_PROXY_HOPS", 1)
    request = _request_con_headers(
        {"x-forwarded-for": "8.8.8.8, 9.9.9.9, 203.0.113.9"}
    )

    assert client_ip(request) == "203.0.113.9"


def test_el_swagger_de_la_propia_api_sigue_funcionando(client, crear_usuario):
    """Same-origin: el /docs vive en el mismo host que la API, así que su
    Origin no está en la lista de dominios del frontend pero es legítimo."""
    usuario = crear_usuario(email="swagger@pruebas.olivosport.co", password="Clave-1234")
    login(client, usuario.email, "Clave-1234")

    respuesta = client.post("/api/v1/auth/refresh", headers={"Origin": "http://testserver"})

    assert respuesta.status_code == 200


# --- Contraseñas --------------------------------------------------------


def test_una_contrasena_mas_larga_que_bcrypt_se_rechaza():
    """bcrypt solo mira 72 bytes y trunca el resto sin avisar: sin este
    límite, dos contraseñas con los mismos 72 bytes iniciales sirven la
    una por la otra."""
    with pytest.raises(ValidationError, match="72 bytes"):
        UserCreate(
            name="Cliente",
            email="largo@pruebas.olivosport.co",
            password="A" * 73,
            accepted_terms=True,
        )


def test_el_limite_se_cuenta_en_bytes_no_en_caracteres():
    with pytest.raises(ValidationError, match="72 bytes"):
        # 37 "ñ" = 74 bytes en UTF-8, aunque sean 37 caracteres.
        SetPasswordRequest(new_password="ñ" * 37)

    assert SetPasswordRequest(new_password="ñ" * 36).new_password


def test_las_contrasenas_obvias_se_rechazan():
    for password in ["12345678", "Password123", "olivosport"]:
        with pytest.raises(ValidationError, match="demasiado común"):
            SetPasswordRequest(new_password=password)


def test_una_contrasena_normal_pasa():
    assert SetPasswordRequest(new_password="Camiseta-Verde-2026").new_password
