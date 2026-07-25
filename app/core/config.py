"""
Configuración centralizada de la aplicación.

Toda variable de entorno se lee UNA sola vez, aquí. El resto del código
importa `settings` en vez de llamar a os.getenv disperso por archivos.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    SUPABASE_URL: str | None = None
    SUPABASE_KEY: str | None = None
    SECRET_KEY: str
    ENVIRONMENT: str = "local"

    # Expiración del access token (JWT), en minutos. Corto a propósito:
    # si se roba, la ventana de uso es chica. La sesión larga la maneja
    # el refresh token de abajo.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15

    # Refresh token: vive en cookie httpOnly, no en el JWT ni en el body.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"

    # Google OAuth: el "Client ID" de tu proyecto en Google Cloud Console
    # (OAuth consent screen / Credentials). Se usa para verificar que un
    # id_token realmente fue emitido para TU aplicación.
    GOOGLE_CLIENT_ID: str | None = None

    # Wompi (pasarela de pagos). En Sandbox estas llaves empiezan con
    # "pub_test_", "prv_test_", etc. En producción, con "pub_prod_".
    WOMPI_PUBLIC_KEY: str | None = None
    WOMPI_PRIVATE_KEY: str | None = None
    WOMPI_INTEGRITY_SECRET: str | None = None
    WOMPI_EVENTS_SECRET: str | None = None
    # Colombia: siempre COP.
    WOMPI_CURRENCY: str = "COP"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Instancia única reutilizada en todo el proyecto
settings = Settings()