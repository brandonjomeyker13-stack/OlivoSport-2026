"""Reglas de negocio de User: aquí va todo lo que NO es una simple query."""

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories import user_repository


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def register_user(
    db: Session, *, name: str, email: str, password: str, accepted_terms: bool
) -> User:
    if user_repository.get_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError(f"El email {email} ya está registrado.")

    password_hash = hash_password(password)
    return user_repository.create(
        db,
        name=name,
        email=email,
        password_hash=password_hash,
        accepted_terms=accepted_terms,
    )


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = user_repository.get_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Email o contraseña incorrectos.")
    if not user.is_active:
        raise InvalidCredentialsError("El usuario está inactivo.")
    return user


def update_profile(db: Session, *, user: User, name: str | None, email: str | None) -> User:
    if email is not None and email != user.email:
        if user_repository.get_by_email(db, email) is not None:
            raise EmailAlreadyRegisteredError(f"El email {email} ya está registrado.")
        user.email = email
    if name is not None:
        user.name = name
    db.commit()
    db.refresh(user)
    return user


def delete_account(db: Session, *, user: User) -> None:
    user_repository.delete(db, user)