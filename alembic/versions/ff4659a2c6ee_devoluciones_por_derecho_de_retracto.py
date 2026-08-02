"""devoluciones por derecho de retracto

Revision ID: ff4659a2c6ee
Revises: a2374800a354
Create Date: 2026-08-02 00:00:17.432561

Solo agrega tablas nuevas: no toca ni borra nada de lo que ya existe, así
que es segura de correr sobre la base con datos.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff4659a2c6ee"
down_revision: str | Sequence[str] | None = "a2374800a354"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ESTADOS = sa.Enum(
    "REQUESTED",
    "APPROVED",
    "REJECTED",
    "RECEIVED",
    "REFUNDED",
    "CANCELLED",
    name="returnstatus",
)


def upgrade() -> None:
    op.create_table(
        "order_returns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("status", _ESTADOS, nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("admin_note", sa.String(length=500), nullable=True),
        sa.Column("refund_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("refund_reference", sa.String(length=100), nullable=True),
        sa.Column("restocked", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_returns_id"), "order_returns", ["id"], unique=False)
    op.create_index(
        op.f("ix_order_returns_order_id"), "order_returns", ["order_id"], unique=False
    )

    op.create_table(
        "order_return_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("return_id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["return_id"], ["order_returns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "return_id", "order_item_id", name="uq_order_return_items_item"
        ),
    )
    op.create_index(
        op.f("ix_order_return_items_id"), "order_return_items", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_order_return_items_order_item_id"),
        "order_return_items",
        ["order_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_return_items_return_id"),
        "order_return_items",
        ["return_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_order_return_items_return_id"), table_name="order_return_items")
    op.drop_index(
        op.f("ix_order_return_items_order_item_id"), table_name="order_return_items"
    )
    op.drop_index(op.f("ix_order_return_items_id"), table_name="order_return_items")
    op.drop_table("order_return_items")
    op.drop_index(op.f("ix_order_returns_order_id"), table_name="order_returns")
    op.drop_index(op.f("ix_order_returns_id"), table_name="order_returns")
    op.drop_table("order_returns")
    # Postgres deja el tipo ENUM vivo aunque se borre la tabla que lo usa:
    # sin esto, volver a subir la migración falla con "type returnstatus
    # already exists".
    _ESTADOS.drop(op.get_bind(), checkfirst=True)
