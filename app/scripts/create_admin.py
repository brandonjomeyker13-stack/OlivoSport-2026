"""
Crea un usuario admin o promueve uno existente a admin, desde la línea
de comandos (nunca por un endpoint público — eso sería un agujero de
seguridad enorme).

Uso (desde la raíz del proyecto, con el .env / variables de entorno
correctas para DATABASE_URL):

    python scripts/create_admin.py admin@olivosport.com "Nombre Admin" "contraseña-segura"

Si el email ya existe, lo promueve a is_admin=True en vez de crear un
usuario duplicado. La contraseña solo se usa si el usuario es nuevo.

En Render: Dashboard -> tu servicio -> pestaña "Shell" -> correr el
mismo comando ahí (ya tiene las env vars de producción cargadas).
"""

import sys

sys.path.insert(0, ".")

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402


def main() -> None:
    if len(sys.argv) != 4:
        print('Uso: python scripts/create_admin.py <email> "<nombre>" "<password>"')
        sys.exit(1)

    email, name, password = sys.argv[1], sys.argv[2], sys.argv[3]

    if len(password) < 8:
        print("La contraseña debe tener al menos 8 caracteres.")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()

        if user:
            if user.is_admin:
                print(f"'{email}' ya era admin. Nada que hacer.")
            else:
                user.is_admin = True
                db.commit()
                print(f"Usuario existente '{email}' promovido a admin.")
        else:
            user = User(
                name=name,
                email=email,
                password_hash=hash_password(password),
                is_admin=True,
            )
            db.add(user)
            db.commit()
            print(f"Admin '{email}' creado correctamente.")
    finally:
        db.close()


if __name__ == "__main__":
    main()