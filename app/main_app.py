"""
App de FastAPI. Se corre con:

    uvicorn app.main:app --reload

(el `main.py` de la raíz sigue siendo solo para crear las tablas, no lo
mezcles con este archivo).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import auth, cart, orders, products, webhooks
from app.core.limiter import limiter
from app.core.security_headers import SecurityHeadersMiddleware

app = FastAPI(title="OlivoSport API", version="1.0.0")

# Rate limit global para proteger principalmente /auth/login y /auth/register.
# Los límites puntuales se definen en cada endpoint con @limiter.limit(...).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SecurityHeadersMiddleware)

# CORS para orígenes locales y dominios Lovable. El regex cubre el subdominio
# de preview, que cambia por proyecto/sesión.
# allow_credentials=True es OBLIGATORIO ahora que el refresh token viaja
# en una cookie httpOnly cross-site (Lovable != dominio del backend); sin
# esto el navegador ni siquiera la manda. Por eso NO se puede usar "*" en
# allow_origins/allow_origin_regex — el navegador lo rechaza cuando hay
# credentials de por medio, así que la lista de orígenes de abajo debe
# mantenerse explícita.
origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.(lovable\.app|lovableproject\.com)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(cart.router, prefix="/api/v1/cart", tags=["cart"])
app.include_router(orders.router, prefix="/api/v1/orders", tags=["orders"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])


@app.get("/")
def root():
    return {"message": "OlivoSport API está corriendo"}


@app.get("/health")
def health_check():
    return {"status": "ok"}"""
App de FastAPI. Se corre con:

    uvicorn app.main:app --reload

(el `main.py` de la raíz sigue siendo solo para crear las tablas, no lo
mezcles con este archivo).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1 import auth, cart, orders, products, webhooks
from app.core.limiter import limiter
from app.core.security_headers import SecurityHeadersMiddleware

logger = logging.getLogger("olivosport.errors")

app = FastAPI(title="OlivoSport API", version="1.0.0")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Red de seguridad para CUALQUIER error no controlado.

    Sin esto, un error inesperado (ej. una tabla que falta, un bug) se
    propaga crudo: el cliente ve un stack trace o, peor, el navegador lo
    reporta como error de CORS porque nunca llega a pasar por el
    middleware de CORS. Con este handler siempre se responde con un JSON
    limpio (sin detalles internos) y sigue pasando por CORS/headers como
    cualquier respuesta normal — además queda logueado server-side con
    el traceback completo para poder revisarlo en Render.
    """
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Ocurrió un error inesperado de nuestro lado. Ya quedó "
            "registrado — inténtalo de nuevo en un momento."
        },
    )

# Rate limit global para proteger principalmente /auth/login y /auth/register.
# Los límites puntuales se definen en cada endpoint con @limiter.limit(...).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SecurityHeadersMiddleware)

# CORS para orígenes locales y dominios Lovable. El regex cubre el subdominio
# de preview, que cambia por proyecto/sesión.
# allow_credentials=True es OBLIGATORIO ahora que el refresh token viaja
# en una cookie httpOnly cross-site (Lovable != dominio del backend); sin
# esto el navegador ni siquiera la manda. Por eso NO se puede usar "*" en
# allow_origins/allow_origin_regex — el navegador lo rechaza cuando hay
# credentials de por medio, así que la lista de orígenes de abajo debe
# mantenerse explícita.
origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.(lovable\.app|lovableproject\.com)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(products.router, prefix="/api/v1/products", tags=["products"])
app.include_router(cart.router, prefix="/api/v1/cart", tags=["cart"])
app.include_router(orders.router, prefix="/api/v1/orders", tags=["orders"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])


@app.get("/")
def root():
    return {"message": "OlivoSport API está corriendo"}


@app.get("/health")
def health_check():
    return {"status": "ok"}