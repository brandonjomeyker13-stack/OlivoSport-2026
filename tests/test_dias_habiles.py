"""Conteo de días hábiles colombianos (la base del plazo de retracto).

Colombia mueve casi todos sus festivos al lunes siguiente (Ley Emiliani),
así que contar "5 días" a mano se equivoca varias veces al año — y cada
error acá le quita o le regala días de un derecho al cliente.
"""

from datetime import date, datetime, timezone

from app.core.dias_habiles import ZONA_HORARIA, es_habil, fin_del_plazo, sumar_dias_habiles


def test_una_semana_normal_son_cinco_dias_habiles():
    # Lunes 7 de septiembre de 2026, una semana sin festivos.
    assert sumar_dias_habiles(date(2026, 9, 7), 5) == date(2026, 9, 14)


def test_el_fin_de_semana_no_cuenta():
    # Entregado un viernes: sábado y domingo se saltan.
    assert sumar_dias_habiles(date(2026, 9, 4), 5) == date(2026, 9, 11)


def test_los_festivos_colombianos_no_cuentan():
    """El 12 de enero de 2026 es Reyes movido al lunes (Ley Emiliani).
    Contando solo fines de semana daría el 12; con el festivo, el 13."""
    assert not es_habil(date(2026, 1, 12))
    assert sumar_dias_habiles(date(2026, 1, 5), 5) == date(2026, 1, 13)


def test_un_festivo_en_la_mitad_corre_el_vencimiento():
    """El 7 de agosto de 2026 (Batalla de Boyacá) cae viernes: un pedido
    entregado el lunes 3 no vence el 10 sino el 11."""
    assert not es_habil(date(2026, 8, 7))
    assert sumar_dias_habiles(date(2026, 8, 3), 5) == date(2026, 8, 11)


def test_el_plazo_vence_al_final_del_dia_hora_colombia():
    entrega = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)

    vence = fin_del_plazo(entrega, 5)

    local = vence.astimezone(ZONA_HORARIA)
    assert local.date() == date(2026, 9, 14)
    assert (local.hour, local.minute) == (23, 59)


def test_una_entrega_de_noche_no_pierde_un_dia_de_plazo():
    """8pm del lunes en Bogotá ya es martes en UTC. Si el plazo se contara
    en UTC, el cliente perdería un día completo."""
    lunes_de_noche = datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc)  # 7 sep, 8pm Bogotá

    assert fin_del_plazo(lunes_de_noche, 5).astimezone(ZONA_HORARIA).date() == date(
        2026, 9, 14
    )
