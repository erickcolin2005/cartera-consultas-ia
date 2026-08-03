"""
El diccionario del catalogo describe las vistas REALES.

POR QUE ESTA PRUEBA EXISTE
---------------------------
`catalogo.yaml` alimenta tres cosas, y una de ellas es **el texto que se envia
al modelo**. Si el diccionario omite una columna, el modelo no sabe que existe;
si nombra una que no existe, el modelo la usara y el motor rechazara la
consulta. En los dos casos el usuario recibe un fallo cuya causa esta en un
fichero de datos que nadie estaba comprobando.

Al construir el contexto de I-4 se midio por primera vez, y el diccionario
estaba **materialmente incompleto**:

  - `consulta.propietarios` no aparecia en absoluto — una relacion entera que
    el guardian permite y que el modelo no habria sabido que existe.
  - `consulta.pagos` no documentaba `valor` ni `medio_pago`: las dos columnas
    del dinero. "Cuanto se recaudo" era inexpresable.
  - Ni `cuotas` ni `pagos` documentaban `unidad_codigo`, **la clave con la que
    se hace cualquier union**. Sin ella no hay una sola consulta de dos tablas.

El hueco venia del diseño (`modelo-datos.md` §7.1), no de la transcripcion. Es
el tipo de defecto que no se ve leyendo —el documento parece completo— y que
aparece en cuanto alguien intenta usarlo para lo que fue escrito.

LO QUE ESTA PRUEBA NO COMPRUEBA
--------------------------------
Que las descripciones de negocio sean BUENAS. Solo que el conjunto de columnas
coincide. La calidad de la prosa la mide C1 sobre el banco, no esto.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]

CATALOGO = yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))

# Claves subrogadas. Se documentan como claves de union y nada mas: son la
# UNICA forma de llegar a `consulta.propietarios`, porque el nombre esta
# desnormalizado en `unidades` pero `fecha_alta` no.
CLAVES_DE_UNION = {"id", "unidad_id", "cuota_id", "propietario_id"}


def _documentadas() -> dict[str, set[str]]:
    return {
        c["relacion"]: {col["n"] for col in c["columnas"]}
        for c in CATALOGO["conceptos"]
    }


@pytest.fixture(scope="module")
def columnas_reales(conexion_owner) -> dict[str, set[str]]:
    """Se lee con el DUEÑO a proposito.

    El rol de la aplicacion no puede leer `information_schema` —se le revoco el
    uso del esquema—, y eso es la contencion funcionando. Comprobarlo desde el
    rol restringido seria imposible, y bajarle la guardia para poder medir
    seria cambiar el sistema para que la prueba pase.
    """
    reales: dict[str, set[str]] = {}
    for rel in CATALOGO["relaciones_permitidas"]:
        esquema, nombre = rel.split(".")
        filas = conexion_owner.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (esquema, nombre),
        ).fetchall()
        reales[rel] = {f[0] for f in filas}
    return reales


def test_todas_las_relaciones_permitidas_estan_en_el_diccionario(columnas_reales):
    """Una relacion que el guardian permite y el diccionario calla es una
    relacion que el modelo nunca usara: permitida y a la vez invisible."""
    faltan = set(columnas_reales) - set(_documentadas())
    assert not faltan, (
        f"El guardian permite {sorted(faltan)} pero el diccionario no las "
        f"describe. El modelo no sabra que existen."
    )


@pytest.mark.parametrize("relacion", sorted(CATALOGO["relaciones_permitidas"]))
def test_el_diccionario_no_omite_ninguna_columna_real(relacion, columnas_reales):
    """Toda columna de la vista tiene que estar documentada."""
    doc = _documentadas().get(relacion, set())
    faltan = columnas_reales[relacion] - doc
    assert not faltan, (
        f"{relacion}: la vista publica {sorted(faltan)} y el diccionario no lo "
        f"dice. El modelo no puede usar lo que no sabe que existe."
    )


@pytest.mark.parametrize("relacion", sorted(CATALOGO["relaciones_permitidas"]))
def test_el_diccionario_no_inventa_columnas(relacion, columnas_reales):
    """Y ninguna documentada puede faltar en la vista.

    Es el sentido MAS peligroso de los dos: una columna inventada no da un
    hueco, da una consulta que el modelo escribe con confianza y que el motor
    rechaza. El usuario ve un fallo sin causa visible.
    """
    doc = _documentadas().get(relacion, set())
    sobran = doc - columnas_reales[relacion]
    assert not sobran, (
        f"{relacion}: el diccionario describe {sorted(sobran)} y la vista no "
        f"las tiene. El modelo escribira SQL contra columnas inexistentes."
    )


def test_las_claves_de_union_estan_documentadas(columnas_reales):
    """Sin clave de union no hay consulta de dos tablas.

    Se comprueba aparte porque es el caso que mas duele y el que mas facil
    pasa inadvertido: el diccionario puede parecer completo —cada relacion con
    sus columnas de negocio— y aun asi no permitir una sola union.
    """
    doc = _documentadas()
    for relacion, reales in columnas_reales.items():
        for columna in sorted(reales & (CLAVES_DE_UNION | {"unidad_codigo"})):
            assert columna in doc.get(relacion, set()), (
                f"{relacion}.{columna} es una clave de union y no esta "
                f"documentada. Sin ella el modelo no puede unir nada."
            )


def test_los_valores_permitidos_apuntan_a_columnas_que_existen(columnas_reales):
    """`valores_permitidos` y `rangos` se envian al modelo como hechos sobre
    columnas concretas. Si apuntan a una columna que no existe, son ruido."""
    for bloque in ("valores_permitidos", "rangos"):
        for clave in CATALOGO[bloque]:
            esquema, relacion, columna = clave.split(".")
            rel = f"{esquema}.{relacion}"
            assert rel in columnas_reales, f"{bloque}: {rel} no es una relación permitida"
            assert columna in columnas_reales[rel], (
                f"{bloque}: {clave} apunta a una columna que la vista no tiene."
            )
