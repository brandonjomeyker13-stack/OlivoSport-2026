"""Acceso a datos de User. Solo queries, sin reglas de negocio."""

from sqlalchemy.orm import Session

from app.models.user import User


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_by_google_id(db: Session, google_id: str) -> User | None:
    return db.query(User).filter(User.google_id == google_id).first()


def create_google_user(
    db: Session,
    *,
    name: str,
    email: str,
    google_id: str,
    password_hash: str | None = None,
    accepted_terms: bool,
) -> User:
    from datetime import datetime, timezone

    user = User(
        name=name,
        email=email,
        password_hash=password_hash,
        google_id=google_id,
        accepted_terms=accepted_terms,
        accepted_terms_at=datetime.now(timezone.utc) if accepted_terms else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def set_google_id(db: Session, user: User, google_id: str) -> User:
    user.google_id = google_id
    db.commit()
    db.refresh(user)
    return user


def link_google_and_clear_password(db: Session, user: User, google_id: str) -> User:
    """Vincula Google a una cuenta que ya existía por contraseña, Y
    invalida esa contraseña anterior.

    A propósito: el registro por contraseña de este proyecto no verifica
    el email, así que alguien pudo haber registrado antes una cuenta con
    el correo de otra persona. Al limpiar password_hash, en el momento
    en que el dueño real del correo entra con Google, cualquier
    contraseña que alguien más haya puesto deja de servir.
    """
    user.google_id = google_id
    user.password_hash = None
    db.commit()
    db.refresh(user)
    return user


def list_all(db: Session, skip: int = 0, limit: int = 100) -> list[User]:
    return db.query(User).offset(skip).limit(limit).all()


def create(
    db: Session, *, name: str, email: str, password_hash: str, accepted_terms: bool
) -> User:
    from datetime import datetime, timezone

    user = User(
        name=name,
        email=email,
        password_hash=password_hash,
        accepted_terms=accepted_terms,
        accepted_terms_at=datetime.now(timezone.utc) if accepted_terms else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete(db: Session, user: User) -> None:
    db.delete(user)
    db.commit()