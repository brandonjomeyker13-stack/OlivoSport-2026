"""Días hábiles colombianos.

La Ley 1480 cuenta el derecho de retracto en *días hábiles*, no calendario:
un pedido entregado un viernes vence el viernes siguiente, y si en el medio
cae un festivo, vence un día después. Colombia además mueve casi todos sus
festivos al lunes siguiente (Ley Emiliani), así que la lista no se puede
escribir a mano: se saca de `holidays`, que ya implementa esa regla.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import holidays

UTC = timezone.utc

# La tienda vende en Colombia: el plazo se cuenta en días locales, no en
# UTC. Sin esto, un pedido entregado a las 8pm de Bogotá (que en UTC ya es
# el día siguiente) perdería un día completo de plazo.
ZONA_HORARIA = ZoneInfo("America/Bogota")

_FESTIVOS = holidays.country_holidays("CO")


def es_habil(dia: date) -> bool:
    return dia.weekday() < 5 and dia not in _FESTIVOS


def sumar_dias_habiles(desde: date, dias: int) -> date:
    """El día de partida NO cuenta (el plazo corre desde el día siguiente
    a la entrega), y los días festivos y fines de semana se saltan."""
    dia = desde
    restantes = dias
    while restantes > 0:
        dia += timedelta(days=1)
        if es_habil(dia):
            restantes -= 1
    return dia


def fin_del_plazo(desde: datetime, dias_habiles: int) -> datetime:
    """Instante exacto (en UTC) en que se vence un plazo de N días hábiles
    contados desde `desde`.

    El plazo vence al FINAL del último día hábil, hora de Colombia: si el
    quinto día hábil es un martes, el cliente tiene hasta las 11:59:59pm de
    ese martes. Cortar a la hora exacta de la entrega le quitaría horas de
    un derecho que la ley le da por días completos.
    """
    # Postgres devuelve estas fechas con zona, pero SQLite (los tests) las
    # devuelve sin ella. Una fecha sin zona se interpreta como UTC, que es
    # la zona en la que la app las guarda.
    if desde.tzinfo is None:
        desde = desde.replace(tzinfo=UTC)

    ultimo_dia = sumar_dias_habiles(desde.astimezone(ZONA_HORARIA).date(), dias_habiles)
    return datetime.combine(ultimo_dia, time.max, tzinfo=ZONA_HORARIA).astimezone(UTC)
