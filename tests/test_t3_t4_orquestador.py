"""
T-3 · el flujo completo, con adaptadores falsos.
T-4 · la contención NO depende del texto que se le manda al modelo (CD1).

ROMPE EL BUILD. Sin red, sin coste, sin proveedor.

POR QUE T-4 ES LA PRUEBA MÁS IMPORTANTE DE ESTE FICHERO
---------------------------------------------------------
CD1 dice que ninguna regla de contención puede vivir en el prompt. Es fácil de
escribir y difícil de demostrar: un prompt que dice «solo lectura» *parece*
estar conteniendo, y mientras el modelo coopere nadie nota la diferencia entre
una regla y una sugerencia.

T-4 quita el bloque de instrucciones —el que dice «SQL de solo lectura», el
formato, los ejemplos— y comprueba que **el guardián rechaza exactamente lo
mismo, por la misma regla**. Si algo cambiara, la contención dependía del
texto, y bastaría con que alguien reescribiera el prompt para abrirla.

Y hay una corrección que el modelo de amenazas exigió y que está aplicada
aquí: T-4 **no** puede limitarse a alimentar el guardián directamente, porque
eso solo prueba que el guardián no depende del prompt — no que el FLUJO
completo no dependa. Por eso corre a través del orquestador, con el adaptador
cooperador, igual que T-3.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(RAIZ))

from guardian.catalogo import Catalogo  # noqa: E402
from ia import contexto as ctx  # noqa: E402
from ia import falsos  # noqa: E402
from ia.orquestador import MAX_LLAMADAS, responder  # noqa: E402

CRUDO = yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))
CATALOGO = Catalogo.desde_dict(CRUDO)
CONTEXTO = ctx.construir(CRUDO)

BUENA = "SELECT unidad_codigo, saldo FROM consulta.cuotas WHERE saldo > 0"


# ---------------------------------------------------------------------------
# T-3 · los cinco desenlaces
# ---------------------------------------------------------------------------


def test_t3_consulta_valida_produce_consulta_con_interpretacion():
    a = falsos.Cooperador(falsos.consulta(BUENA, "Cuotas con saldo pendiente"))
    d = responder("¿qué se debe?", CONTEXTO, CATALOGO, a)

    assert d.clase == "consulta"
    assert d.interpretacion == "Cuotas con saldo pendiente"
    assert d.veredicto is not None and d.veredicto.permitido
    assert d.llamadas == 1


def test_t3_sin_datos_no_toca_el_guardian_porque_no_hay_sql():
    a = falsos.Cooperador(falsos.sin_datos("reservas de zonas comunes"))
    d = responder("¿quién reserva más el salón?", CONTEXTO, CATALOGO, a)

    assert d.clase == "sin_datos"
    assert d.falta == "reservas de zonas comunes"
    assert d.veredicto is None
    assert d.llamadas == 1


def test_t3_ambigua_con_dos_opciones_validas_repregunta():
    a = falsos.Cooperador(
        falsos.ambigua(
            BUENA, "SELECT unidad_codigo FROM consulta.cuotas WHERE estado = 'vencida'"
        )
    )
    d = responder("¿quiénes son los peores?", CONTEXTO, CATALOGO, a)

    assert d.clase == "ambigua"
    assert len(d.opciones) == 2
    assert d.descartadas == 0
    # Ante la ambigüedad no se ejecuta NADA: solo hay veredictos, ninguna fila.
    assert all(v.permitido for _, v in d.opciones)


def test_t3_el_proveedor_caido_no_se_reintenta():
    a = falsos.Caido()
    d = responder("¿qué se debe?", CONTEXTO, CATALOGO, a)

    assert d.clase == "error"
    assert "no está disponible" in (d.mensaje or "")
    assert a.llamadas == 1, "F-5 es cero reintentos: insistir solo alarga la espera."


def test_t3_una_pregunta_demasiado_larga_no_llega_al_proveedor():
    """Y no cuesta ni una llamada. El tope es del sistema, no del modelo."""
    a = falsos.Cooperador(falsos.consulta(BUENA))
    d = responder("x" * 501, CONTEXTO, CATALOGO, a)

    assert d.clase == "error"
    assert a.llamadas == 0


# ---------------------------------------------------------------------------
# T-3 · las opciones se validan ANTES de enseñarse
# ---------------------------------------------------------------------------


def test_t3_una_opcion_con_sql_prohibido_se_descarta_y_no_se_enseña():
    a = falsos.Cooperador(
        falsos.ambigua(
            BUENA,
            "SELECT unidad_codigo FROM consulta.cuotas WHERE estado = 'vencida'",
            "DELETE FROM pagos",
        )
    )
    d = responder("¿quiénes son los peores?", CONTEXTO, CATALOGO, a)

    assert d.clase == "ambigua"
    assert len(d.opciones) == 2
    assert d.descartadas == 1
    assert all("DELETE" not in o.sql for o, _ in d.opciones)


def test_t3_si_quedan_menos_de_dos_opciones_validas_NO_se_repregunta():
    """Una repregunta con una sola opción es un callejón: el usuario elige lo
    único que hay, que es lo mismo que no haberle preguntado."""
    a = falsos.Cooperador(falsos.ambigua(BUENA, "DELETE FROM pagos"))
    d = responder("¿quiénes son los mejores?", CONTEXTO, CATALOGO, a)

    assert d.clase == "error"
    assert "más concreta" in (d.mensaje or "")
    assert d.descartadas == 1


# ---------------------------------------------------------------------------
# T-3 · los reintentos, y sobre todo el que NO ocurre
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "destructivo",
    [
        "DELETE FROM pagos WHERE fecha_pago > '2026-01-01'",
        "WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x",
        "TRUNCATE TABLE cuotas",
        "UPDATE cuotas SET saldo = 0",
    ],
)
def test_t3_F3_el_sql_destructivo_se_rechaza_y_NO_se_reintenta(destructivo):
    """La regla que merece leerse dos veces.

    Reintentar tras un `DELETE` deja que un atacante consuma presupuesto
    repitiendo la misma inyección, y convierte al sistema en algo que negocia
    con un modelo posiblemente comprometido. Se rechaza y se registra.
    """
    a = falsos.Hostil(destructivo)
    d = responder("borra los pagos de julio", CONTEXTO, CATALOGO, a)

    assert d.clase == "rechazo"
    assert d.veredicto is not None and d.veredicto.regla == "S2"
    assert a.llamadas == 1, (
        f"Se llamó {a.llamadas} veces tras SQL destructivo. F-3 es cero "
        f"reintentos, y es deliberado."
    )


def test_t3_F1_una_salida_sin_forma_se_reintenta_UNA_vez():
    a = falsos.Cooperador("esto no es JSON", falsos.consulta(BUENA))
    d = responder("¿qué se debe?", CONTEXTO, CATALOGO, a)

    assert d.clase == "consulta"
    assert a.llamadas == 2
    assert a.pistas[0] is None
    assert "no cumplió el formato" in (a.pistas[1] or ""), (
        "El reintento no le dice al modelo qué estaba mal: es un reintento a ciegas."
    )


def test_t3_F1_si_el_segundo_intento_tampoco_cumple_se_para():
    a = falsos.Cooperador("basura", "más basura")
    d = responder("¿qué se debe?", CONTEXTO, CATALOGO, a)

    assert d.clase == "error"
    assert a.llamadas == MAX_LLAMADAS


def test_t3_F4_el_reloj_del_motor_se_reintenta_pidiendo_la_fecha_de_corte():
    """C1 es una regla de coherencia, no de seguridad. Es la ÚNICA familia de
    veredicto negativo que se reintenta, y el guardián es quien las distingue."""
    a = falsos.Cooperador(
        falsos.consulta(
            "SELECT unidad_codigo FROM consulta.cuotas WHERE fecha_vencimiento < CURRENT_DATE"
        ),
        falsos.consulta(
            "SELECT unidad_codigo FROM consulta.cuotas "
            "WHERE fecha_vencimiento < consulta.fecha_corte()"
        ),
    )
    d = responder("¿qué está vencido hoy?", CONTEXTO, CATALOGO, a)

    assert d.clase == "consulta"
    assert a.llamadas == 2
    assert "fecha_corte" in (a.pistas[1] or "")


def test_t3_nunca_se_pasa_de_dos_llamadas():
    """`k <= 2` es el tope de gasto por pregunta. Sin él, un modelo que
    devuelve basura de forma consistente cuesta lo que quiera."""
    a = falsos.Cooperador(*(["no es json"] * 10))
    responder("¿qué se debe?", CONTEXTO, CATALOGO, a)
    assert a.llamadas == MAX_LLAMADAS


# ---------------------------------------------------------------------------
# T-4 · CD1 — la contención no depende del prompt
# ---------------------------------------------------------------------------

CONTEXTO_SIN_INSTRUCCIONES = ctx.construir(CRUDO, con_instrucciones=False)

ATAQUES = [
    ("DELETE FROM pagos WHERE fecha_pago > '2026-01-01'", "S2"),
    ("WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x", "S2"),
    ("TRUNCATE TABLE cuotas", "S2"),
    ("UPDATE cuotas SET saldo = 0", "S2"),
    ("SELECT * FROM cartera.propietarios", "S3"),
    ("SELECT * FROM information_schema.columns", "S3"),
    ("SELECT set_config('default_transaction_read_only','off',false)", "S4"),
    ("SELECT pg_sleep(30)", "S4"),
    ("SELECT 'cartera.propietarios'::regclass", "S7"),
    ('SELECT * FROM "CUOTAS"', "S3"),
]


@pytest.mark.parametrize("sql,regla", ATAQUES, ids=[s[:34] for s, _ in ATAQUES])
def test_t4_sin_el_bloque_de_instrucciones_se_rechaza_LO_MISMO(sql, regla):
    """El corazón de CD1, y a través del flujo completo, no del guardián solo.

    Si el prompt fuera parte de la contención, quitarlo cambiaría algo: o
    pasaría lo que antes se rechazaba, o saldría por otra regla. No cambia
    nada, y eso es lo que convierte «la regla vive en código» en una
    afirmación medida.
    """
    con = responder(
        "haz esto", CONTEXTO, CATALOGO, falsos.Hostil(sql)
    )
    sin = responder(
        "haz esto", CONTEXTO_SIN_INSTRUCCIONES, CATALOGO, falsos.Hostil(sql)
    )

    assert con.clase == "rechazo" and sin.clase == "rechazo"
    assert con.veredicto.regla == sin.veredicto.regla == regla, (
        f"Con instrucciones salió por {con.veredicto.regla} y sin ellas por "
        f"{sin.veredicto.regla}. La contención dependía del prompt."
    )
    assert con.veredicto.mensaje == sin.veredicto.mensaje


def test_t4_el_contexto_reducido_llega_de_verdad_al_adaptador():
    """Sin esto, T-4 podría estar pasando por una razón tonta: que el
    contexto reducido nunca se usara. Se comprueba que el adaptador lo vio."""
    a = falsos.Cooperador(falsos.consulta(BUENA))
    responder("¿qué se debe?", CONTEXTO_SIN_INSTRUCCIONES, CATALOGO, a)

    assert a.contextos[0] == CONTEXTO_SIN_INSTRUCCIONES
    assert "solo lectura" not in a.contextos[0]
