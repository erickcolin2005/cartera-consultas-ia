"""
Invariantes de los datos sinteticos (D9, RN-01 ... RN-07, modelo-datos §5.2/§5.3).

QUE PRUEBA
----------
1. Que los datos siguen siendo los versionados (conteos + suma de comprobacion).
2. Que cumplen las siete reglas de negocio.
3. Que contienen los hechos que el banco NECESITA para poder medirse.

POR QUE EL PUNTO 3 NO ES OPCIONAL
---------------------------------
"Los datos se diseñan, no se sortean". Si las tres opciones de A-03 dieran la
misma lista de morosos, la repregunta seria teatro y C3 mediria una conducta
vacia. Si la unidad 302 no existiera, N-05 no tendria respuesta. Estos hechos
son requisitos del banco, no adorno del generador — y por eso tienen prueba.

ESTA PRUEBA NO ES T-8 NI SUSTITUYE A NINGUNA DE LAS TRECE.
Es la afirmacion de invariancia que T-2 (degradacion) usara mas adelante:
con la capa 3 apagada, estos numeros tienen que salir IDENTICOS.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

DATOS = Path(__file__).resolve().parents[1] / "datos"
HUELLA = json.loads((DATOS / "huella.json").read_text(encoding="utf-8"))


def _bloques_huella() -> dict[str, str]:
    texto = (DATOS / "huella.sql").read_text(encoding="utf-8")
    partes = re.split(r"^--\s*@huella\s+(\w+)\s*$", texto, flags=re.MULTILINE)
    return {partes[i]: partes[i + 1].strip() for i in range(1, len(partes), 2)}


BLOQUES = _bloques_huella()


def _uno(conexion, sql: str, *args):
    with conexion.cursor() as cur:
        cur.execute(sql, args or None)
        return cur.fetchone()


def _todos(conexion, sql: str, *args):
    with conexion.cursor() as cur:
        cur.execute(sql, args or None)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 1 · Los datos son los versionados
# ---------------------------------------------------------------------------

def test_conteos_exactos(conexion_owner):
    obtenido = dict(_todos(conexion_owner, BLOQUES["conteos"]))
    assert obtenido == HUELLA["conteos"]


def test_suma_de_comprobacion(conexion_owner):
    obtenido = _uno(conexion_owner, BLOQUES["suma"])[0]
    assert obtenido == HUELLA["suma_de_comprobacion"], (
        "Los datos cargados no son los versionados. Si el cambio fue deliberado, "
        "recalcula valores-esperados.md y vuelve a medir el banco EN EL MISMO COMMIT; "
        "si no lo fue, alguien escribio en la base."
    )


# ---------------------------------------------------------------------------
# 2 · Las siete reglas de negocio
# ---------------------------------------------------------------------------

def test_rn07_fecha_de_corte_fija(conexion_owner):
    """Sin fecha de corte fija, 'quien debe mas de tres meses' cambia de
    respuesta cada dia y el porcentaje del README caduca en 24 horas."""
    assert _uno(conexion_owner, "SELECT consulta.fecha_corte()")[0] == date(2026, 7, 5)


def test_rn02_administracion_vence_el_dia_10(conexion_owner):
    fuera = _uno(conexion_owner, """
        SELECT count(*) FROM cartera.cuotas
        WHERE concepto = 'administracion'
          AND (fecha_emision <> periodo
               OR fecha_vencimiento <> periodo + INTERVAL '9 days')
    """)[0]
    assert fuera == 0


def test_rn05_el_saldo_nunca_es_negativo(conexion_owner):
    """No hay pagos anticipados ni saldos a favor: SUM(pagos) <= valor."""
    excedidas = _uno(conexion_owner, """
        SELECT count(*) FROM (
            SELECT c.id FROM cartera.cuotas c
            JOIN cartera.pagos p ON p.cuota_id = c.id
            GROUP BY c.id, c.valor HAVING SUM(p.valor) > c.valor
        ) t
    """)[0]
    assert excedidas == 0


def test_rn05_todo_pago_se_imputa_a_una_cuota_ya_emitida(conexion_owner):
    anticipados = _uno(conexion_owner, """
        SELECT count(*) FROM cartera.pagos p
        JOIN cartera.cuotas c ON c.id = p.cuota_id
        WHERE p.fecha_pago < c.fecha_emision
    """)[0]
    assert anticipados == 0


def test_rn06_cada_unidad_tiene_un_solo_propietario_y_diez_tienen_varias(conexion_owner):
    """La segunda mitad es N-10: si diera 0, la pregunta no mediria nada."""
    con_varias = _uno(conexion_owner, """
        SELECT count(*) FROM (
            SELECT propietario_id FROM cartera.unidades
            GROUP BY propietario_id HAVING count(*) > 1
        ) t
    """)[0]
    assert con_varias == 10


def test_los_coeficientes_suman_uno(conexion_owner):
    assert _uno(conexion_owner, "SELECT SUM(coeficiente) FROM cartera.unidades")[0] == 1


# ---------------------------------------------------------------------------
# 3 · Los hechos que el banco necesita (modelo-datos §5.3)
# ---------------------------------------------------------------------------

def test_existe_la_unidad_302_con_propietario(conexion_owner):
    """N-05 y M-03 la nombran por su codigo."""
    fila = _uno(conexion_owner, """
        SELECT u.codigo, p.nombre FROM cartera.unidades u
        JOIN cartera.propietarios p ON p.id = u.propietario_id
        WHERE u.codigo = '302'
    """)
    assert fila is not None and fila[1]


def test_la_unidad_101_tiene_pagos_en_2026(conexion_owner):
    """N-08: 'muestrame los pagos de la unidad 101 en 2026'."""
    cuantos = _uno(conexion_owner, """
        SELECT count(*) FROM consulta.pagos
        WHERE unidad_codigo = '101' AND fecha_pago >= DATE '2026-01-01'
    """)[0]
    assert cuantos > 0


def test_las_tres_opciones_de_a03_dan_listas_distintas(conexion_owner):
    """Cualquier saldo vencido / mas de un mes / mas de tres meses.
    Si las tres dieran la misma lista, repreguntar seria teatro."""
    cualquiera, mas_de_un_mes, mas_de_tres_meses = _uno(conexion_owner, """
        SELECT count(DISTINCT unidad_id) FILTER (WHERE dias_vencida > 0),
               count(DISTINCT unidad_id) FILTER (WHERE dias_vencida > 30),
               count(DISTINCT unidad_id) FILTER (WHERE dias_vencida > 90)
        FROM consulta.cuotas
    """)
    assert cualquiera > mas_de_un_mes > mas_de_tres_meses > 0


def test_hay_mora_de_mas_de_seis_meses(conexion_owner):
    assert _uno(conexion_owner,
                "SELECT count(*) FROM consulta.cuotas WHERE dias_vencida > 180")[0] > 0


def test_hay_un_pago_de_julio_aplicado_a_una_cuota_de_mayo(conexion_owner):
    """A-04. Sin este hecho la pregunta es ambigua en el enunciado pero no en
    los datos, y las dos opciones de la repregunta darian lo mismo."""
    cuantos = _uno(conexion_owner, """
        SELECT count(*) FROM consulta.pagos
        WHERE fecha_pago >= DATE '2026-07-01' AND periodo_cuota = DATE '2026-05-01'
    """)[0]
    assert cuantos > 0


def test_hay_derrama_extraordinaria_en_2025_09(conexion_owner):
    """A-02 y N-09: 'facturado' no es solo administracion."""
    cuantas = _uno(conexion_owner, """
        SELECT count(*) FROM cartera.cuotas
        WHERE concepto = 'extraordinaria' AND periodo = DATE '2025-09-01'
    """)[0]
    assert cuantas > 0


def test_existen_los_tres_estados_de_cuota(conexion_owner):
    """'corriente' es lo que mantiene viva la ambiguedad de A-05: la cuota del
    periodo en curso esta emitida y aun no vencida (RN-02 + RN-07)."""
    estados = {fila[0] for fila in _todos(conexion_owner,
                                          "SELECT DISTINCT estado FROM consulta.cuotas")}
    assert estados == {"pagada", "vencida", "corriente"}


@pytest.mark.parametrize("consulta_sql, descripcion", [
    ("SELECT count(*) FROM cartera.propietarios WHERE nombre = 'Vercingetorix Qhuazbal Ñemerov'",
     "nombre centinela"),
    ("SELECT count(*) FROM cartera.pagos WHERE referencia = 'CENTINELA-QX7Z-4M91'",
     "referencia centinela"),
])
def test_los_centinelas_de_t5_estan_en_los_datos(conexion_owner, consulta_sql, descripcion):
    """T-5 (fuga al modelo) necesita cadenas improbables: si alguna aparece en
    lo que se envia al proveedor, la fuga es inequivoca."""
    assert _uno(conexion_owner, consulta_sql)[0] == 1, f"falta el {descripcion}"


def test_los_rangos_publicados_en_el_catalogo_son_ciertos(conexion_owner):
    """catalogo.yaml §7.2 los publica en pantalla. Si mienten, D-D falla:
    '¿cuanto se recaudo en 2023?' devolveria vacio y se leeria como cero."""
    periodo_min, periodo_max = _uno(conexion_owner,
                                    "SELECT min(periodo), max(periodo) FROM cartera.cuotas")
    pago_min, pago_max = _uno(conexion_owner,
                              "SELECT min(fecha_pago), max(fecha_pago) FROM cartera.pagos")
    assert (periodo_min, periodo_max) == (date(2025, 1, 1), date(2026, 7, 1))
    assert date(2025, 1, 10) <= pago_min and pago_max <= date(2026, 7, 4)
