"""Reglas de negocio de User: aquí va todo lo que NO es una simple query."""

import logging

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories import user_repository

logger = logging.getLogger("olivosport.users")


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class GoogleAccountConflictError(Exception):
    pass


class TermsNotAcceptedError(Exception):
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
    # user.password_hash puede ser None (cuenta creada solo con Google):
    # ese usuario no tiene contraseña, así que nunca puede pasar esta
    # verificación por más que "adivine" cualquier cosa.
    if user is None or user.password_hash is None or not verify_password(
        password, user.password_hash
    ):
        raise InvalidCredentialsError("Email o contraseña incorrectos.")
    if not user.is_active:
        raise InvalidCredentialsError("El usuario está inactivo.")
    return user


def authenticate_google(
    db: Session,
    *,
    email: str,
    google_id: str,
    name: str,
    accepted_terms: bool,
    password: str | None = None,
) -> User:
    existing_by_google = user_repository.get_by_google_id(db, google_id)
    if existing_by_google is not None:
        if not existing_by_google.is_active:
            raise InvalidCredentialsError("El usuario está inactivo.")
        return existing_by_google

    existing_by_email = user_repository.get_by_email(db, email)
    if existing_by_email is not None:
        if existing_by_email.google_id is not None and existing_by_email.google_id != google_id:
            # Caso raro: el email ya está vinculado a OTRA cuenta de
            # Google distinta. Esto no debería pasar en flujo normal.
            raise GoogleAccountConflictError(
                "Este email ya está vinculado a otra cuenta de Google."
            )
        logger.info(
            "Vinculando Google a cuenta existente por email (user_id=%s); "
            "se invalida su contraseña anterior por seguridad.",
            existing_by_email.id,
        )
        return user_repository.link_google_and_clear_password(
            db, existing_by_email, google_id
        )

    if not accepted_terms:
        raise TermsNotAcceptedError(
            "Debes aceptar los Términos y Condiciones y la Política de "
            "Tratamiento de Datos para registrarte."
        )

    # Cuenta nueva creada por Google: si el frontend manda una contraseña
    # (se le pide UNA sola vez, en este primer registro), la guardamos
    # para que de ahí en adelante también pueda entrar con email+contraseña
    # sin que se la vuelvan a pedir.
    password_hash = hash_password(password) if password else None
    return user_repository.create_google_user(
        db, name=name, email=email, google_id=google_id, password_hash=password_hash
    )


def link_google_account(db: Session, *, user: User, email: str, google_id: str) -> User:
    if email != user.email:
        raise GoogleAccountConflictError(
            "El email de la cuenta de Google no coincide con el de tu perfil."
        )
    existing = user_repository.get_by_google_id(db, google_id)
    if existing is not None and existing.id != user.id:
        raise GoogleAccountConflictError(
            "Esta cuenta de Google ya está vinculada a otro usuario."
        )
    return user_repository.set_google_id(db, user, google_id)


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