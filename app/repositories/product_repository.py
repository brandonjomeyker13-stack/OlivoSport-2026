"""Acceso a datos de Product. Solo queries, sin reglas de negocio."""

from sqlalchemy.orm import Session

from app.models.product import Product


def get_by_id(db: Session, product_id: int) -> Product | None:
    return db.query(Product).filter(Product.id == product_id).first()


def list_all(db: Session, skip: int = 0, limit: int = 100) -> list[Product]:
    return (
        db.query(Product)
        .order_by(Product.id)
        .offset(skip)
        .limit(limit)
        .all()
    )


def create(db: Session, *, name: str, color: str, size: str, price, stock: int) -> Product:
    product = Product(
        name=name,
        color=color,
        size=size,
        price=price,
        stock=stock,
        in_stock=stock > 0,
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