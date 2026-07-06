"""Reglas de negocio de User: aquí va todo lo que NO es una simple query."""

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories import user_repository


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def register_user(db: Session, *, name: str, email: str, password: str) -> User:
    if user_repository.get_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError(f"El email {email} ya está registrado.")

    password_hash = hash_password(password)
    return user_repository.create(db, name=name, email=email, password_hash=password_hash)


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = user_repository.get_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Email o contraseña incorrectos.")
    if not user.is_active:
        raise InvalidCredentialsError("El usuario está inactivo.")
    return user