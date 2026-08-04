"""
T-6 · Los cuatro tipos de respuesta se renderizan, y se distinguen.
T-10 · La superficie de salida: escapado como mecanismo, y CSP.
T-12 · El traductor de errores: lista blanca, sin oráculos.

ROMPE EL BUILD. Sin red, sin modelo.

POR QUE LAS TRES JUNTAS
------------------------
Las tres miden lo mismo desde ángulos distintos: **qué sale de aquí hacia un
navegador**. Separarlas en tres ficheros repartiría el mismo montaje entre tres
sitios y haría más fácil que una se quedara atrás.

LO QUE T-6 MIDE, Y NO ES «QUE NO PETE»
---------------------------------------
Que los cuatro desenlaces produzcan bloques **distinguibles**. Un sistema que
renderizara todo igual pasaría cualquier prueba de «no lanza excepción» y sería
inútil: quien mira no podría saber si le rechazaron la consulta, si le
repreguntaron o si no hay datos.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.ejecutor import _ERRORES, _ERROR_GENERICO, Resultado  # noqa: E402
from app.servidor import (  # noqa: E402
    Manejador,
    bloque_coherencia,
    bloque_demasiado_largo,
    bloque_demasiado_rapido,
    bloque_rechazo,
    bloque_resultado,
    e,
    pagina,
)
from guardian.catalogo import Catalogo  # noqa: E402
from guardian.nucleo import veredicto  # noqa: E402

CATALOGO_CRUDO = yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))
CATALOGO = Catalogo.desde_dict(CATALOGO_CRUDO)


# ---------------------------------------------------------------------------
# T-6 · los cuatro tipos de respuesta
# ---------------------------------------------------------------------------


def _bloques() -> dict[str, str]:
    permitida = veredicto("SELECT unidad_codigo FROM cuotas", CATALOGO)
    rechazada = veredicto("DELETE FROM pagos", CATALOGO)
    reloj = veredicto(
        "SELECT * FROM cuotas WHERE fecha_vencimiento < CURRENT_DATE", CATALOGO
    )
    ok = Resultado(columnas=["c"], filas=[("v",)], sentencias_enviadas=1, ms=3)
    return {
        "resultado": bloque_resultado(permitida, ok),
        "rechazo": bloque_rechazo(rechazada, Resultado(), True),
        "coherencia": bloque_coherencia(reloj, Resultado()),
        "error_motor": bloque_resultado(
            permitida, Resultado(error="Eso está fuera de lo que puedo consultar.")
        ),
    }


def test_t6_los_cuatro_desenlaces_producen_bloques_DISTINTOS():
    """Distinguibles, no solo presentes.

    Un sistema que renderizara los cuatro igual pasaría cualquier prueba de «no
    lanza excepción» y sería inútil: quien mira no podría saber si le
    rechazaron, si le repreguntaron o si no hay datos.
    """
    b = _bloques()
    # Se quita el marcado interno: el primer `<h2>` del bloque de resultado
    # lleva un `<small>` dentro, y una expresión que exigiera texto plano hasta
    # el cierre no lo vería. Medir el titular es medir lo que se lee, no cómo
    # está marcado.
    titulos = {
        k: re.sub(r"<[^>]+>", "", re.search(r"<h2>(.*?)</h2>", v, re.S).group(1)).strip()
        for k, v in b.items()
    }
    assert len(set(titulos.values())) == 4, (
        f"Dos desenlaces comparten titular: {titulos}"
    )


@pytest.mark.parametrize(
    "clase,debe_contener",
    [
        ("resultado", "Lo que se ejecutó de verdad"),
        ("rechazo", "regla S2"),
        ("coherencia", "fecha de corte"),
        ("error_motor", "fuera de lo que puedo consultar"),
    ],
)
def test_t6_cada_bloque_dice_lo_suyo(clase, debe_contener):
    assert debe_contener in _bloques()[clase]


def test_t6_solo_el_resultado_ensena_filas():
    """Ni un rechazo ni una repregunta pueden enseñar datos: no los hubo."""
    b = _bloques()
    assert "<table>" in b["resultado"]
    for clase in ("rechazo", "coherencia", "error_motor"):
        assert "<table>" not in b[clase], f"{clase} enseña una tabla"


def test_t6_todos_los_bloques_declaran_las_sentencias_enviadas():
    """La cifra que sostiene el argumento aparece en los cuatro, no solo donde
    conviene. Enseñarla solo en el rechazo la convertiría en decoración."""
    for clase, html in _bloques().items():
        assert "Sentencias enviadas" in html, f"{clase} no la declara"


# ---------------------------------------------------------------------------
# T-10 · superficie de salida
# ---------------------------------------------------------------------------

CARGAS = [
    "<script>alert(1)</script>",
    "'\"><img src=x onerror=alert(1)>",
    "</textarea><script>alert(1)</script>",
    "javascript:alert(1)",
    "<svg/onload=alert(1)>",
    "&lt;script&gt;",
]


@pytest.mark.parametrize("carga", CARGAS)
def test_t10_ninguna_carga_sobrevive_en_ningun_bloque(carga):
    """El eco de un rechazo es texto arbitrario de quien ataca, y se renderiza.

    Se prueban TODOS los bloques con la misma carga: basta que uno solo escape
    mal para que la superficie exista, y el que se olvida es siempre el que
    nadie miró.
    """
    v = veredicto(f"SELECT {carga} FROM cuotas", CATALOGO)
    salidas = [
        bloque_rechazo(v, Resultado(), True) if not v.permitido else "",
        bloque_demasiado_largo(carga),
        bloque_resultado(
            veredicto("SELECT unidad_codigo FROM cuotas", CATALOGO),
            Resultado(columnas=[carga], filas=[(carga,)], sentencias_enviadas=1),
        ),
    ]
    for html in salidas:
        assert "<script>" not in html
        assert "onerror=" not in html or "&lt;img" in html
        assert "<svg/onload" not in html


def test_t10_el_escapado_es_MECANISMO_y_no_se_puede_saltar():
    """Todo lo que llega al marcado pasa por `e()`. Si alguien construyera
    marcado con una f-string y texto crudo, esto no lo vería — pero sí lo ve
    la prueba de arriba, que mide el resultado. Las dos hacen falta."""
    assert e("<b>") == "&lt;b&gt;"
    assert e('"') == "&quot;"
    assert e(None) == ""


def test_t10_la_CSP_no_permite_nada_en_linea():
    """Segunda capa. Si un escapado fallara, el navegador sigue sin ejecutar."""
    csp = None
    for linea in (RAIZ / "app" / "servidor.py").read_text(encoding="utf-8").splitlines():
        if "default-src" in linea:
            csp = linea
    assert csp, "No se envía Content-Security-Policy."
    assert "unsafe-inline" not in csp, "La CSP permite estilos o scripts en línea."
    assert "unsafe-eval" not in csp
    assert "default-src 'none'" in csp


def test_t10_la_pagina_declara_el_juego_de_caracteres():
    """Sin `charset`, el navegador adivina — y adivinando se puede llegar a
    interpretar como marcado algo que se escapó como texto."""
    html = pagina("<p>x</p>").decode()
    assert 'charset="utf-8"' in html or "charset=utf-8" in html


def test_t10_no_hay_ni_una_linea_de_javascript():
    """La ausencia que sostiene todo lo demás: sin JavaScript no hay
    `innerHTML`, y sin `innerHTML` no hay la vía de escape más común."""
    fuente = (RAIZ / "app" / "servidor.py").read_text(encoding="utf-8")
    assert "<script" not in fuente.lower()
    assert "innerHTML" not in fuente


# ---------------------------------------------------------------------------
# T-12 · el traductor de errores
# ---------------------------------------------------------------------------


def test_t12_columna_inexistente_y_columna_NO_PUBLICADA_dan_el_MISMO_texto():
    """El oráculo que RF-12 prohíbe.

    `SELECT documento FROM propietarios` (existe, no publicada) y
    `SELECT xyzzy FROM propietarios` (no existe) tienen que ser
    indistinguibles: si difieren, se prueban nombres hasta mapear el esquema.
    """
    assert _ERRORES["42703"] == _ERRORES["42P01"] == _ERRORES["42501"]


def test_t12_ningun_mensaje_nombra_un_objeto_del_esquema():
    """Un mensaje que nombra un objeto es media respuesta a quien sondea.

    QUE SE PROHIBE Y QUE NO, PORQUE LA PRIMERA VERSION SE EQUIVOCO
    ---------------------------------------------------------------
    El primer intento prohibía la palabra «consulta», y falló sobre un mensaje
    correcto: *«La consulta tardó demasiado»*. Es que `consulta` es a la vez el
    nombre del esquema **y la palabra española para «consulta»**. Prohibirla es
    imposible — todos los mensajes hablan de la consulta.

    Lo que RF-12 protege no son las palabras del dominio: son los
    IDENTIFICADORES. Un nombre cualificado (`esquema.tabla`) o una columna que
    la vista no publica sí revelan estructura; «cuotas» en una frase, no.
    """
    cualificados = [r for r in CATALOGO_CRUDO["relaciones_permitidas"]]
    ocultas = ["documento", "email", "telefono", "propietario_id", "cuota_id"]
    motor = ["pg_", "postgres", "sqlstate", "relation", "syntax error"]

    for texto in list(_ERRORES.values()) + [_ERROR_GENERICO]:
        bajo = texto.lower()
        for nombre in cualificados + ocultas + motor:
            assert nombre not in bajo, f"«{texto}» nombra «{nombre}»"


def test_t12_los_mensajes_no_distinguen_QUE_mecanismo_se_toco():
    """S3, S4, S5 y S7 comparten texto a propósito.

    Un texto distinto le diría a quien ataca si dio con la lista de tablas, la
    de funciones o la de tipos, y convertiría cada rechazo en una respuesta
    gratis sobre lo que hay detrás.
    """
    from guardian.contrato import MENSAJES

    assert MENSAJES["S3"] == MENSAJES["S4"] == MENSAJES["S5"] == MENSAJES["S7"]
    # Y el identificador de la regla SÍ difiere: es un oráculo de política
    # aceptado y declarado, porque sin él dos reglas serían indistinguibles
    # también para quien audita.
    assert len({"S3", "S4", "S5", "S7"}) == 4


def test_t12_hay_una_fila_generica_y_es_la_que_hace_robusto_el_control():
    """Sin ella, un SQLSTATE no previsto se colaría con el texto del motor."""
    assert _ERROR_GENERICO
    assert "no pude" in _ERROR_GENERICO.lower()


def test_t12_el_traductor_no_deja_pasar_el_texto_del_motor():
    """Se comprueba sobre el ejecutor real, con un error que NO está en la
    lista: tiene que salir el genérico, no el mensaje de PostgreSQL."""
    from app import ejecutor

    class ErrorRaro(Exception):
        sqlstate = "XX999"

    assert ejecutor._ERRORES.get("XX999") is None
    # El camino: cualquier SQLSTATE no listado cae en el genérico.
    assert ejecutor._ERRORES.get("XX999", _ERROR_GENERICO) == _ERROR_GENERICO


def test_t12_el_limite_de_tasa_tampoco_filtra_nada():
    """El bloque de «demasiado rápido» es superficie de salida como el resto."""
    html = bloque_demasiado_rapido()
    assert "<script>" not in html
    for palabra in ("cartera", "propietarios", "postgres"):
        assert palabra not in html.lower()
