"""Acceso a datos de Product. Solo queries, sin reglas de negocio."""

from sqlalchemy.orm import Session

from app.models.product import Product


def get_by_id(db: Session, product_id: int) -> Product | None:
    return db.query(Product).filter(Product.id == product_id).first()


def get_by_id_for_update(db: Session, product_id: int) -> Product | None:
    """Igual que get_by_id, pero bloquea la fila (SELECT ... FOR UPDATE)
    hasta que la transacción actual termine (commit/rollback).

    Úsalo SOLO dentro de un flujo donde quien llama controla el commit
    final (no hagas commit adentro de un loop que use esto, o sueltas el
    lock a mitad de camino y dos pagos simultáneos pueden volver a leer
    el mismo stock "viejo").
    """
    return (
        db.query(Product)
        .filter(Product.id == product_id)
        .with_for_update()
        .first()
    )


def apply_stock_delta(db: Session, product: Product, delta: int) -> Product:
    """Suma `delta` al stock (negativo para descontar), SIN hacer commit.

    Pensado para usarse junto con get_by_id_for_update dentro de una
    transacción más grande (ej. procesar un pedido completo con varios
    productos) donde el commit lo hace el que orquesta todo al final.
    """
    product.stock = max(0, product.stock + delta)
    product.in_stock = product.stock > 0
    return product


def list_all(
    db: Session, skip: int = 0, limit: int = 100, category_id: int | None = None
) -> list[Product]:
    query = db.query(Product)
    if category_id is not None:
        query = query.filter(Product.category_id == category_id)
    return query.order_by(Product.id).offset(skip).limit(limit).all()


def create(
    db: Session,
    *,
    name: str,
    color: str,
    size: str,
    price,
    stock: int,
    category_id: int,
    cost=None,
) -> Product:
    product = Product(
        name=name,
        color=color,
        size=size,
        price=price,
        stock=stock,
        in_stock=stock > 0,
        category_id=category_id,
        cost=cost,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def update_stock(db: Session, product: Product, new_stock: int) -> Product:
    product.stock = new_stock
    product.in_stock = new_stock > 0
    db.commit()
    db.refresh(product)
    return product


def update(db: Session, product: Product, **fields) -> Product:
    """Actualiza solo los campos que vengan en `fields` (no None)."""
    for key, value in fields.items():
        if value is not None:
            setattr(product, key, value)

    # Si cambiaron el stock, mantenemos in_stock consistente.
    if "stock" in fields and fields["stock"] is not None:
        product.in_stock = fields["stock"] > 0

    db.commit()
    db.refresh(product)
    return product


def delete(db: Session, product: Product) -> None:
    db.delete(product)
    db.commit()