"""telefono del usuario

`users.phone` ya existía en el modelo pero no en ninguna migración, así que
`alembic check` fallaba y una base creada desde cero se quedaba sin la
columna. Si la base ya la tiene (se agregó a mano), la migración no hace
nada en vez de reventar.

Revision ID: 888f50771db4
Revises: a2374800a354
Create Date: 2026-08-03 12:06:08.334009

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '888f50771db4'
down_revision: str | Sequence[str] | None = 'a2374800a354'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tiene_columna() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == "phone" for col in inspector.get_columns("users"))


def upgrade() -> None:
    """Upgrade schema."""
    if not _tiene_columna():
        op.add_column('users', sa.Column('phone', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    if _tiene_columna():
        op.drop_column('users', 'phone')
