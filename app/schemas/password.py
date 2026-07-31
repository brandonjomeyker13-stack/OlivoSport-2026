"""
Tipo compartido para cualquier contraseña que entre por la API, para que
las reglas sean las mismas en registro, en Google y al cambiarla.
"""

from typing import Annotated

from pydantic import AfterValidator, Field

# bcrypt solo mira los primeros 72 BYTES y descarta el resto sin avisar:
# sin este límite, "<72 bytes>hola" y "<72 bytes>chau" son la misma
# contraseña para el login, y el usuario cree que tiene una más larga.
# Se cuenta en bytes, no en caracteres: una "ñ" o un emoji ocupan varios.
MAX_PASSWORD_BYTES = 72

# Las que se prueban de primeras en cualquier ataque de fuerza bruta. No
# pretende ser una lista completa (para eso está el rate limit); es para
# atajar lo más obvio, que además cumple el mínimo de 8 caracteres.
_PASSWORDS_COMUNES = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "password",
        "password1",
        "password123",
        "qwertyui",
        "qwerty123",
        "11111111",
        "00000000",
        "abc12345",
        "iloveyou",
        "princess",
        "football",
        "baseball",
        "sunshine",
        "colombia",
        "contrasena",
        "contraseña",
        "olivosport",
        "administrador",
    }
)


def _validar_password(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"La contraseña no puede pasar de {MAX_PASSWORD_BYTES} bytes "
            "(los acentos y emojis cuentan como varios)."
        )
    if value.lower() in _PASSWORDS_COMUNES:
        raise ValueError("Esa contraseña es demasiado común. Elige otra.")
    return value


Password = Annotated[str, Field(min_length=8), AfterValidator(_validar_password)]
