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

from app.api.v1 import auth, cart, orders, products
from app.core.limiter import limiter

app = FastAPI(title="OlivoSport API", version="1.0.0")

# Rate limiting global (protege sobre todo /auth/login y /auth/register
# de ataques de fuerza bruta). Los límites puntuales se definen en cada
# endpoint con @limiter.limit(...).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Orígenes fijos: solo desarrollo local. Todo lo de Lovable (preview,
# iframe de edición, y el sitio publicado) se cubre con el regex de abajo,
# porque el subdominio de preview cambia por proyecto/sesión.
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


@app.get("/")
def root():
    return {"message": "OlivoSport API está corriendo"}


@app.get("/health")
def health_check():
    return {"status": "ok"}