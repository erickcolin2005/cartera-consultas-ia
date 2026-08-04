"""
I-5 · Editar la consulta y volver a enviarla, con las mismas comprobaciones.

ROMPE EL BUILD.

QUE SE MIDE, Y POR QUE NO ES OBVIO
------------------------------------
La pantalla enseña la consulta en una caja editable y dice: *"cámbiale un
SELECT por un DELETE y envíala; se rechaza igual"*. Esa frase es una promesa
sobre una **ausencia**: que no existe una vía privilegiada para el texto que el
sistema acaba de aceptar.

Las promesas sobre ausencias son las que más fácil se rompen sin que nadie lo
note, porque nada falla el día que aparece el atajo. Estas pruebas la fijan.

LO QUE NO SE PRUEBA AQUI
-------------------------
No se prueba el HTML. Se prueba la propiedad: el SQL editado entra por la misma
puerta y recibe el mismo veredicto que si nunca hubiera pasado nada antes. Si
mañana la pantalla cambia de forma, esto sigue siendo lo que hay que sostener.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.servidor import caja_para_editar  # noqa: E402
from guardian.catalogo import Catalogo  # noqa: E402
from guardian.nucleo import veredicto  # noqa: E402

CATALOGO = Catalogo.desde_dict(
    yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))
)

ACEPTADA = "SELECT unidad_codigo, saldo FROM cuotas WHERE saldo > 0"


# ---------------------------------------------------------------------------
# La propiedad: no hay vía privilegiada
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "editada,regla",
    [
        ("DELETE FROM pagos", "S2"),
        ("UPDATE cuotas SET saldo = 0", "S2"),
        ("TRUNCATE TABLE cuotas", "S2"),
        ("SELECT * FROM cartera.propietarios", "S3"),
        ("SELECT set_config('default_transaction_read_only','off',false)", "S4"),
        ("SELECT 'cartera.propietarios'::regclass", "S7"),
        ("SELECT 1; DROP TABLE cuotas", "S1"),
    ],
    ids=lambda x: x[:26] if isinstance(x, str) else x,
)
def test_editar_una_consulta_aceptada_para_hacerla_destructiva_no_sirve(editada, regla):
    """El caso que la pantalla invita a probar, y que tiene que fallar.

    Primero se comprueba que la original SÍ pasa —si no, la prueba no
    demostraría nada: estaría rechazando algo que ya se rechazaba— y luego que
    la editada sale por la regla que le toca.
    """
    assert veredicto(ACEPTADA, CATALOGO).permitido, (
        "La consulta de partida ya se rechazaba: el caso no mide lo que dice."
    )

    v = veredicto(editada, CATALOGO)
    assert not v.permitido, f"«{editada}» pasó tras editarla."
    assert v.regla == regla, f"salió por {v.regla} y se esperaba {regla}"


def test_el_veredicto_de_una_consulta_no_depende_de_lo_que_paso_antes():
    """El guardián no tiene memoria, y aquí es donde eso importa.

    Si el veredicto dependiera del historial —"esta viene de una que ya
    aprobé"— la caja editable sería un agujero. Se comprueba juzgando la misma
    carga destructiva antes y después de una consulta legítima: mismo
    veredicto, misma regla, mismo mensaje.
    """
    antes = veredicto("DELETE FROM pagos", CATALOGO)
    veredicto(ACEPTADA, CATALOGO)
    despues = veredicto("DELETE FROM pagos", CATALOGO)

    assert (antes.permitido, antes.regla, antes.mensaje) == (
        despues.permitido, despues.regla, despues.mensaje
    )


def test_reejecutar_la_misma_consulta_da_el_mismo_veredicto():
    """Reenviar sin cambiar nada no puede cambiar el desenlace."""
    primero = veredicto(ACEPTADA, CATALOGO)
    segundo = veredicto(ACEPTADA, CATALOGO)
    assert primero.sql_a_ejecutar == segundo.sql_a_ejecutar


# ---------------------------------------------------------------------------
# La caja, como superficie de salida
# ---------------------------------------------------------------------------


def test_la_caja_lleva_el_original_y_no_el_reserializado():
    """Si llevara el reserializado, editarlo y reenviarlo lo envolvería dos
    veces y el usuario estaría corrigiendo un texto que no escribió."""
    import html

    v = veredicto(ACEPTADA, CATALOGO)
    caja = caja_para_editar(v.eco, "etiqueta", "botón")

    # Se desescapa para comparar: el `>` del WHERE sale como `&gt;`, que es el
    # escapado funcionando. Comparar el marcado crudo mediría el escapado, no
    # el contenido, y el escapado ya tiene sus propias pruebas abajo.
    assert ACEPTADA in html.unescape(caja)
    assert "_acotado" not in caja, "La caja lleva el envoltorio del sistema."
    assert "_acotado" in (v.sql_a_ejecutar or ""), (
        "El reserializado ya no lleva envoltorio: la prueba mide otra cosa."
    )


@pytest.mark.parametrize(
    "hostil",
    [
        "</textarea><script>alert(1)</script>",
        "\" onmouseover=\"alert(1)",
        "<img src=x onerror=alert(1)>",
        "SELECT '<b>negrita</b>' FROM cuotas",
    ],
)
def test_la_caja_escapa_lo_que_le_metan(hostil):
    """El eco de un rechazo es texto arbitrario de quien ataca, y ahora va
    dentro de un `<textarea>`. Cerrar la etiqueta a mano es el escape obvio."""
    caja = caja_para_editar(hostil, "etiqueta", "botón")

    assert "<script>" not in caja
    assert "</textarea><" not in caja
    assert "onerror=" not in caja or "&lt;img" in caja
    # Y no se pierde nada: es evidencia, no adorno.
    assert "&lt;" in caja or "&quot;" in caja or "&amp;" in caja


def test_la_caja_no_pierde_ni_un_caracter_del_eco():
    """Lo que se enseña para editar tiene que ser lo que llegó, entero.

    Un truncado silencioso aquí sería peor que en cualquier otro sitio: el
    usuario reenviaría una consulta distinta de la que cree estar reenviando.
    """
    import html

    largo = "SELECT " + "a" * 3000 + " FROM cuotas"
    caja = caja_para_editar(largo, "etiqueta", "botón")
    dentro = caja.split(">", 1)[1]  # basta con que el texto esté completo
    assert html.unescape(dentro).find(largo) >= 0
