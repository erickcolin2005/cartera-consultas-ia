"""
T-2 · Degradación: con la capa 3 APAGADA, ¿qué sigue conteniendo?

ROMPE EL BUILD. Necesita la base de datos.

QUE MIDE, Y POR QUE ES DISTINTA DE TODO LO DEMAS
--------------------------------------------------
El resto de las pruebas comprueban que el guardián rechaza. Ésta comprueba lo
contrario: **qué pasa cuando el guardián no está**.

El proyecto afirma contención en capas. Esa afirmación solo significa algo si
se puede quitar una y ver que las de abajo aguantan. Sin esta prueba, «cuatro
capas» es una figura retórica: nadie ha comprobado nunca que la segunda exista
por separado.

COMO SE APAGA LA CAPA 3
------------------------
Se sustituye el guardián por uno NULO que permite todo, y se ejecuta el SQL tal
cual contra el motor con la credencial de la aplicación. Es exactamente el
escenario «alguien encontró la forma de saltarse la comprobación previa».

No se toca el guardián real: se le pasa al ejecutor un veredicto fabricado. Si
esta prueba modificara el guardián, mediría un sistema que no existe.

LO QUE ESTA PRUEBA NO PUEDE AFIRMAR
------------------------------------
Que las cuatro excepciones declaradas queden contenidas. **No lo están, y el
diseño lo dice**: el catálogo del motor (M-07, M-12), el límite de filas (M-14)
y el detector por conversión de tipo (M-19) NO tienen respaldo del motor. Esta
prueba las mide igual, y afirma que fallan — porque una excepción declarada que
resultara estar contenida también sería información.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.ejecutor import ejecutar  # noqa: E402
from guardian.contrato import Veredicto  # noqa: E402


def sin_guardian(sql: str) -> Veredicto:
    """Un veredicto NULO: permite lo que sea, sin mirarlo.

    Es la capa 3 apagada. El SQL sale hacia el motor tal cual lo escribió quien
    ataca — sin reserializar, sin límite de filas, sin nada.
    """
    return Veredicto(permitido=True, eco=sql, sql_a_ejecutar=sql)


# ---------------------------------------------------------------------------
# Lo que el MOTOR para solo
# ---------------------------------------------------------------------------

DESTRUCTIVAS = [
    ("borrado", "DELETE FROM consulta.cuotas"),
    ("actualizacion", "UPDATE consulta.cuotas SET saldo = 0"),
    ("insercion", "INSERT INTO consulta.pagos (valor) VALUES (1)"),
    ("vaciado", "TRUNCATE TABLE consulta.cuotas"),
    ("borrado-tabla", "DROP TABLE consulta.cuotas"),
    ("creacion", "CREATE TABLE intruso (x integer)"),
    ("privilegios", "GRANT ALL ON SCHEMA consulta TO consulta_ro"),
    ("tabla-base", "SELECT * FROM cartera.propietarios"),
    ("catalogo-info", "SELECT * FROM information_schema.columns"),
    ("columna-oculta", "SELECT documento FROM consulta.propietarios"),
]


@pytest.mark.parametrize(
    "caso,sql", DESTRUCTIVAS, ids=[c for c, _ in DESTRUCTIVAS]
)
def test_t2_el_motor_contiene_esto_aunque_el_guardian_no_este(caso, sql):
    """Capas 1 y 2 solas: privilegios del rol y alcance de las vistas.

    Si alguna de éstas se ejecutara, la contención dependería ENTERAMENTE del
    guardián — y el proyecto estaría afirmando cuatro capas donde hay una.
    """
    r = ejecutar(sin_guardian(sql))

    assert r.error is not None, (
        f"«{sql}» SE EJECUTÓ con el guardián apagado. La contención de este "
        f"caso depende solo de la capa 3."
    )
    # Y llegó al motor de verdad: si el contador dijera 0, la prueba estaría
    # midiendo que no se intentó, no que se rechazó.
    assert r.sentencias_enviadas == 1, (
        "La sentencia no llegó al motor: esta prueba no mide lo que dice."
    )


def test_t2_los_datos_no_cambian_aunque_se_intente_todo(conexion_ro):
    """La comprobación que cierra el argumento.

    No basta con que cada sentencia devuelva error: hay que verificar que
    NINGUNA dejó rastro. Un borrado parcial que además fallara al final habría
    pasado las aserciones de arriba.
    """
    antes = conexion_ro.execute(
        "SELECT count(*), COALESCE(SUM(saldo), 0) FROM consulta.cuotas"
    ).fetchone()

    for _, sql in DESTRUCTIVAS:
        ejecutar(sin_guardian(sql))

    despues = conexion_ro.execute(
        "SELECT count(*), COALESCE(SUM(saldo), 0) FROM consulta.cuotas"
    ).fetchone()

    assert antes == despues, (
        f"Los datos cambiaron con el guardián apagado: {antes} -> {despues}"
    )


# ---------------------------------------------------------------------------
# Las excepciones DECLARADAS: aquí el motor NO contiene, y se mide
# ---------------------------------------------------------------------------


def test_t2_el_catalogo_del_motor_NO_esta_contenido_y_asi_se_declara():
    """Excepción 1 del diseño (M-07, M-12).

    `pg_catalog` no filtra por privilegios: un rol sin ningún permiso sobre una
    tabla puede enumerarla. Con el guardián apagado, esto se ejecuta.

    La prueba afirma el FALLO. Si algún día dejara de ejecutarse, algo cambió
    —en el motor o en la configuración— y hay que enterarse: una excepción que
    se cierra sola es tan informativa como una que se abre.
    """
    r = ejecutar(sin_guardian("SELECT relname FROM pg_class LIMIT 5"))

    assert r.error is None and r.filas, (
        "El catálogo del motor ya no es alcanzable. Es una buena noticia, pero "
        "contradice lo que el README declara como excepción 1: hay que "
        "actualizarlo."
    )


def test_t2_el_limite_de_filas_NO_lo_pone_el_motor():
    """Excepción 3 (M-14). El límite es del sistema, no del motor.

    Con el guardián apagado no hay quien lo imponga: la consulta devuelve todo
    lo que haya. Lo único que queda debajo es `statement_timeout`.
    """
    r = ejecutar(sin_guardian("SELECT unidad_codigo FROM consulta.cuotas"))

    assert r.error is None

    # `hay_mas` es la evidencia, no `len(filas)`. Y la distinción importa: el
    # límite vive en DOS sitios —el guardián lo añade al SQL, y el ejecutor
    # trunca a 100 lo que llegue—, así que apagar solo el guardián no lo quita.
    # La primera versión de esta prueba pedía más de 100 filas y falló con 100
    # exactas: estaba midiendo el truncado del ejecutor, no lo que hizo el
    # motor. `hay_mas` significa que el motor DEVOLVIÓ más de 100.
    assert r.hay_mas, (
        "El motor devolvió 100 filas o menos. Si estuviera limitando él, el "
        "README tendría que dejar de declarar esto como excepción."
    )


def test_t2_el_tiempo_maximo_SI_es_del_motor():
    """Lo que sí respalda a M-13 y M-25: `statement_timeout`.

    Es la única contención que sobrevive al guardián para las consultas
    costosas, y por eso el diseño la nombra como «el único respaldo».
    """
    r = ejecutar(
        sin_guardian(
            "SELECT count(*) FROM consulta.cuotas a, consulta.cuotas b, "
            "consulta.cuotas c, consulta.pagos d"
        )
    )

    assert r.error is not None, "El producto cartesiano terminó: no hubo tope."
    assert "tardó demasiado" in r.error, (
        f"Falló por otra razón: «{r.error}». Se esperaba el tiempo máximo."
    )
