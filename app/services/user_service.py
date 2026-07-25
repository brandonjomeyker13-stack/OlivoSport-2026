"""Reglas de negocio de User: aquí va todo lo que NO es una simple query."""

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories import user_repository


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
    db: Session, *, email: str, google_id: str, name: str, accepted_terms: bool
) -> User:
    existing_by_google = user_repository.get_by_google_id(db, google_id)
    if existing_by_google is not None:
        if not existing_by_google.is_active:
            raise InvalidCredentialsError("El usuario está inactivo.")
        return existing_by_google

    existing_by_email = user_repository.get_by_email(db, email)
    if existing_by_email is not None:
        # Ya existe una cuenta con este email pero SIN vincular a este
        # Google ID. No vinculamos automático: si alguien se registró
        # antes con este email por contraseña (sin verificarlo), un
        # auto-link silencioso le daría a esa cuenta ya existente acceso
        # a la identidad de Google de otra persona. Que lo vincule a
        # propósito, ya logueado con su contraseña.
        raise GoogleAccountConflictError(
            "Ya existe una cuenta con este email. Inicia sesión con tu "
            "contraseña y vincula tu cuenta de Google desde tu perfil."
        )

    if not accepted_terms:
        raise TermsNotAcceptedError(
            "Debes aceptar los Términos y Condiciones y la Política de "
            "Tratamiento de Datos para registrarte."
        )

    return user_repository.create_google_user(db, name=name, email=email, google_id=google_id)


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