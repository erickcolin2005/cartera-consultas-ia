"""
El contexto que sale hacia el proveedor del modelo.

AQUI VIVE T-5(b), QUE ESTABA DECLARADA COMO PENDIENTE
-------------------------------------------------------
T-5 tiene dos mitades. La (a) —estructural, el guardian no tiene por donde
filtrar nada— vive en `test_t5_fuga.py` y estaba completa. La (b) —el texto
que de verdad sale hacia el proveedor— no podia escribirse porque el
constructor de contexto no existia. Ahora existe, y esto es esa mitad.

La diferencia entre las dos no es de grado: (a) demuestra que **no hay via**,
(b) mide **el texto concreto**. Hacen falta las dos, porque el constructor
podria no importar nada prohibido y aun asi llevar una fila escrita a mano.

POR QUE LOS CENTINELAS SON VALORES REALES DE LA BASE
------------------------------------------------------
No se busca «que no haya datos» en abstracto, que no es comprobable. Se toman
valores que SOLO pueden venir de las tablas —un nombre de propietario, un
codigo de unidad, un importe— y se afirma que ninguno aparece en el texto. Si
alguien añadiera «unas cuantas filas de ejemplo para que el modelo entienda
mejor», que es una tentacion razonable y frecuente, esto se pone en rojo.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]

CATALOGO_CRUDO = yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))

import sys  # noqa: E402

sys.path.insert(0, str(RAIZ))

from guardian.catalogo import Catalogo  # noqa: E402
from guardian.nucleo import veredicto  # noqa: E402
from ia import contexto  # noqa: E402

CATALOGO = Catalogo.desde_dict(CATALOGO_CRUDO)
TEXTO = contexto.construir(CATALOGO_CRUDO)


# ---------------------------------------------------------------------------
# T-5(b) · lo que NO puede salir
# ---------------------------------------------------------------------------


def test_t5b_ninguna_fila_de_la_base_aparece_en_el_contexto(conexion_ro):
    """Centinelas tomados del motor. Si alguno aparece, hay fuga."""
    centinelas: list[str] = []
    for consulta, columna in [
        ("SELECT propietario_nombre FROM consulta.unidades LIMIT 5", "nombre"),
        ("SELECT codigo FROM consulta.unidades LIMIT 5", "codigo"),
        ("SELECT DISTINCT referencia FROM consulta.pagos LIMIT 5", "referencia"),
        ("SELECT saldo::text FROM consulta.cuotas WHERE saldo > 0 LIMIT 5", "saldo"),
    ]:
        centinelas += [str(f[0]) for f in conexion_ro.execute(consulta).fetchall()]

    assert centinelas, "No se pudo leer ningún centinela: la prueba no mediría nada."

    filtrados = [c for c in centinelas if c and c in TEXTO]
    assert not filtrados, (
        f"Estos valores salen de las tablas y aparecen en el texto que se envía "
        f"al proveedor: {filtrados}. D6 dice que del contenido de las tablas no "
        f"sale nada."
    )


def test_t5b_el_constructor_no_importa_nada_que_pueda_leer_datos():
    """Estructural, como la mitad (a). Los casos son infinitos; las vías, no."""
    arbol = ast.parse((RAIZ / "ia" / "contexto.py").read_text(encoding="utf-8"))
    prohibidos = {
        "psycopg": "base de datos", "sqlite3": "base de datos",
        "sqlalchemy": "base de datos", "socket": "red", "urllib": "red",
        "requests": "red", "httpx": "red", "http": "red",
        "pathlib": "sistema de ficheros", "os": "entorno",
    }
    for nodo in ast.walk(arbol):
        modulos = []
        if isinstance(nodo, ast.Import):
            modulos = [a.name for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            modulos = [nodo.module]
        for modulo in modulos:
            raiz = modulo.split(".")[0]
            assert raiz not in prohibidos, (
                f"contexto.py importa `{modulo}` ({prohibidos[raiz]}). El "
                f"constructor de contexto recibe el catálogo ya cargado: si "
                f"pudiera leer, podría leer una fila."
            )


def test_t5b_el_contexto_no_depende_de_nada_vivo():
    """Dos llamadas, mismo texto. Sin reloj ni aleatoriedad.

    Importa para el coste: si el prefijo cambiara entre consultas, la tarifa
    reducida por contexto repetido dejaría de aplicar sin que nadie lo note.
    """
    assert contexto.construir(CATALOGO_CRUDO) == contexto.construir(CATALOGO_CRUDO)


# ---------------------------------------------------------------------------
# Lo que SÍ tiene que salir
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relacion", sorted(CATALOGO_CRUDO["relaciones_permitidas"]))
def test_las_cuatro_relaciones_estan_en_el_contexto(relacion):
    assert relacion in TEXTO


def test_todas_las_columnas_documentadas_llegan_al_modelo():
    """Si una columna está en el diccionario y no en el texto, el trabajo de
    documentarla no sirvió de nada."""
    faltan = [
        f"{c['relacion']}.{col['n']}"
        for c in CATALOGO_CRUDO["conceptos"]
        for col in c["columnas"]
        if col["n"] not in TEXTO
    ]
    assert not faltan, f"No llegan al modelo: {faltan}"


def test_las_ausencias_declaradas_llegan_completas():
    """El bloque 7 es lo que hace posible D-D. Sin él, un modelo servicial
    busca el concepto más parecido y responde otra cosa."""
    for ausencia in CATALOGO_CRUDO["NO_hay_datos_de"]:
        assert ausencia in TEXTO


def test_los_rangos_llegan_porque_evitan_el_cero_falso():
    """«¿Cuánto se recaudó en 2023?» sin rangos devuelve una tabla vacía, y una
    tabla vacía se lee como un cero. No es un error: es una respuesta correcta
    a una pregunta mal informada."""
    assert "2025-01-01" in TEXTO and "2026-07-01" in TEXTO
    assert str(CATALOGO_CRUDO["fecha_corte"]) in TEXTO


# ---------------------------------------------------------------------------
# Los pares curados: le enseñan SQL al modelo, así que tienen que ser correctos
# ---------------------------------------------------------------------------


def _sql_de_los_pares() -> list[tuple[str, str]]:
    salida = []
    for pregunta, respuesta in contexto._PARES:
        d = json.loads(respuesta)
        if d["tipo"] == "consulta":
            salida.append((pregunta, d["sql"]))
        elif d["tipo"] == "ambigua":
            salida += [(f"{pregunta} [{o['id']}]", o["sql"]) for o in d["opciones"]]
    return salida


def test_los_pares_curados_son_json_valido_y_del_contrato():
    for pregunta, respuesta in contexto._PARES:
        d = json.loads(respuesta)
        assert d["tipo"] in ("consulta", "ambigua", "sin_datos"), pregunta


@pytest.mark.parametrize(
    "pregunta,sql", _sql_de_los_pares(), ids=[p for p, _ in _sql_de_los_pares()]
)
def test_cada_sql_de_ejemplo_pasa_el_guardian(pregunta, sql):
    """Un ejemplo que el guardián rechazaría le enseñaría al modelo justo lo
    que el sistema no acepta. Peor que no dar ejemplos."""
    v = veredicto(sql, CATALOGO)
    assert v.permitido, f"«{pregunta}»: el guardián lo rechaza por {v.regla}"


@pytest.mark.parametrize(
    "pregunta,sql", _sql_de_los_pares(), ids=[p for p, _ in _sql_de_los_pares()]
)
def test_cada_sql_de_ejemplo_se_ejecuta_y_devuelve_filas(pregunta, sql):
    """Pasar el guardián no basta: puede pasar y fallar en el motor, o
    ejecutarse y devolver cero filas, que enseñaría una consulta inútil."""
    from app.ejecutor import ejecutar

    r = ejecutar(veredicto(sql, CATALOGO))
    assert r.error is None, f"«{pregunta}»: {r.error}"
    assert r.filas, f"«{pregunta}»: se ejecuta pero no devuelve ninguna fila."


def test_los_ejemplos_no_usan_el_banco():
    """Los pares no pueden salir del banco de preguntas.

    Si el modelo viera los casos del banco como ejemplos, C1 mediría cuánto
    recuerda y no cuánto entiende. Es la diferencia entre un examen y una
    respuesta.
    """
    banco = yaml.safe_load((RAIZ / "banco" / "banco.yaml").read_text(encoding="utf-8"))
    texto_banco = json.dumps(banco, ensure_ascii=False).lower()
    for pregunta, _ in contexto._PARES:
        assert pregunta.lower() not in texto_banco, (
            f"«{pregunta}» está en el banco. Usarla como ejemplo invalida C1."
        )


# ---------------------------------------------------------------------------
# CD1 · la contención no puede depender de este texto
# ---------------------------------------------------------------------------


def test_cd1_sin_el_bloque_de_instrucciones_el_material_sigue_entero():
    """Lo que T-4 necesita: quitar las instrucciones sin quitar los hechos.

    Si `con_instrucciones=False` borrara también el esquema, T-4 no probaría
    que la contención no depende del prompt: probaría que un modelo sin
    esquema escribe peor SQL, que es otra cosa y no interesa.
    """
    reducido = contexto.construir(CATALOGO_CRUDO, con_instrucciones=False)

    assert "solo lectura" not in reducido, "El bloque de instrucciones sigue ahí."
    assert "Respondes SIEMPRE" not in reducido
    for relacion in CATALOGO_CRUDO["relaciones_permitidas"]:
        assert relacion in reducido, "Se llevó por delante el esquema."
    assert len(reducido) < len(TEXTO)
