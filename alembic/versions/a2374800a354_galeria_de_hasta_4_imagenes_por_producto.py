"""galeria de hasta 4 imagenes por producto

Cada producto pasa de tener una sola `products.image_url` a tener hasta 4
imágenes en `product_images`. La imagen que ya tenía cargada NO se pierde:
se copia como la principal (position=0) antes de borrar la columna, y al
revertir se devuelve a la columna.

Revision ID: a2374800a354
Revises: f627c998be66
Create Date: 2026-07-31 16:04:51.153288

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a2374800a354'
down_revision: str | Sequence[str] | None = 'f627c998be66'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Las URLs públicas de Supabase son
# .../object/public/product-images/<archivo>. Se guarda ese <archivo>
# aparte porque es lo que hay que mandarle a Supabase para borrarlo.
_MARCA_DEL_BUCKET = "/product-images/"


def _storage_path(image_url: str) -> str | None:
    if _MARCA_DEL_BUCKET not in image_url:
        return None
    return image_url.split(_MARCA_DEL_BUCKET, 1)[1].split("?", 1)[0] or None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('product_images',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('image_url', sa.String(length=500), nullable=False),
    sa.Column('storage_path', sa.String(length=500), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_id', 'position', name='uq_product_images_product_position')
    )
    op.create_index(op.f('ix_product_images_id'), 'product_images', ['id'], unique=False)
    op.create_index(op.f('ix_product_images_product_id'), 'product_images', ['product_id'], unique=False)

    conexion = op.get_bind()
    existentes = conexion.execute(
        sa.text(
            "SELECT id, image_url FROM products "
            "WHERE image_url IS NOT NULL AND image_url <> ''"
        )
    ).fetchall()
    for product_id, image_url in existentes:
        conexion.execute(
            sa.text(
                "INSERT INTO product_images "
                "(product_id, image_url, storage_path, position) "
                "VALUES (:product_id, :image_url, :storage_path, 0)"
            ),
            {
                "product_id": product_id,
                "image_url": image_url,
                "storage_path": _storage_path(image_url),
            },
        )

    op.drop_column('products', 'image_url')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('products', sa.Column('image_url', sa.VARCHAR(length=500), autoincrement=False, nullable=True))

    # Volviendo atrás solo cabe una imagen por producto: se conserva la
    # principal y las demás se pierden (la columna no da para más).
    op.get_bind().execute(
        sa.text(
            "UPDATE products SET image_url = ("
            "  SELECT image_url FROM product_images"
            "  WHERE product_images.product_id = products.id"
            "  ORDER BY position LIMIT 1"
            ")"
        )
    )

    op.drop_index(op.f('ix_product_images_product_id'), table_name='product_images')
    op.drop_index(op.f('ix_product_images_id'), table_name='product_images')
    op.drop_table('product_images')
