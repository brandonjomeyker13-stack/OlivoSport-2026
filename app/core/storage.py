"""
Subida de archivos a Supabase Storage.

Requiere que en el .env SUPABASE_URL y SUPABASE_KEY estén configurados,
y que SUPABASE_KEY sea la clave "service_role" (no la "anon"), porque
solo el service_role puede subir archivos sin pasar por las políticas
de acceso del bucket.
"""

import uuid

from fastapi import HTTPException, UploadFile, status
from supabase import create_client

from app.core.config import settings

BUCKET_NAME = "product-images"

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

# Firmas binarias reales (magic bytes) de cada formato permitido. El
# Content-Type del header lo manda el cliente y se puede falsificar
# fácilmente (ej. subir un .html/.svg con script y decir que es
# image/png); esto verifica los bytes de verdad, no lo que dice el header.
_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    # WEBP: header RIFF....WEBP — el tamaño va en los bytes 4-8, no importa.
    "image/webp": (b"RIFF",),
}


def _detect_real_content_type(contents: bytes) -> str | None:
    for content_type, signatures in _MAGIC_SIGNATURES.items():
        for signature in signatures:
            if contents.startswith(signature):
                if content_type == "image/webp" and contents[8:12] != b"WEBP":
                    continue
                return content_type
    return None


def _get_client():
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_URL / SUPABASE_KEY no están configurados en el .env.",
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


async def upload_product_image(file: UploadFile, product_id: int) -> str:
    """Sube la imagen y devuelve la URL pública para guardar en products.image_url."""

    # Chequeo rápido del header como primer filtro (no es la validación
    # real, solo evita leer el archivo completo si viene claramente mal).
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten imágenes JPG, PNG o WEBP.",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La imagen no puede pesar más de 5 MB.",
        )

    # Validación REAL: los bytes tienen que coincidir con la firma binaria
    # del formato, sin importar lo que diga el Content-Type del header.
    real_content_type = _detect_real_content_type(contents)
    if real_content_type is None or real_content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no es una imagen JPG, PNG o WEBP válida.",
        )

    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[
        real_content_type
    ]
    # Nombre único por producto para evitar sobrescribir el archivo anterior.
    path = f"product-{product_id}-{uuid.uuid4().hex}.{extension}"

    client = _get_client()
    client.storage.from_(BUCKET_NAME).upload(
        path, contents, {"content-type": real_content_type}
    )

    return client.storage.from_(BUCKET_NAME).get_public_url(path)