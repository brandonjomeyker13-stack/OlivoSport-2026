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

    # Config de futuros JWT (cuando agregues login por API)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Instancia única reutilizada en todo el proyecto
settings = Settings()