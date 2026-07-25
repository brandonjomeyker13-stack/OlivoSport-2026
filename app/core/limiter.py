"""
Limiter compartido (slowapi) para proteger endpoints sensibles de fuerza
bruta, principalmente login y registro.

Se limita por IP (get_remote_address). Si en algún momento el hosting
queda detrás de un proxy/CDN que no pasa la IP real, hay que revisar
el header X-Forwarded-For.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# default_limits aplica a TODOS los endpoints que no tengan su propio
# @limiter.limit(...) — antes /products, /cart, /checkout no tenían
# ningún límite y se podían scrapear/bombardear sin restricción.
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])