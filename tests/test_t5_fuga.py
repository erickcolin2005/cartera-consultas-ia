"""
T-5 · Fuga de datos hacia el proveedor del modelo (D6).

ROMPE EL BUILD.

QUE ESTA PRUEBA CUBRE HOY, Y QUE NO
------------------------------------
T-5 tiene dos mitades:

  (a) ESTRUCTURAL — el guardian no puede tocar nada. Se comprueba leyendo el
      codigo fuente del paquete. **Se cubre entera aqui.**
  (b) CENTINELAS en el texto que se envia al proveedor. El constructor de
      contexto todavia no existe (I-4), asi que solo se cubre la parte que ya
      es cierta hoy: que `catalogo.yaml` —la UNICA fuente del texto que se
      enviara— no contiene ni una fila de datos.

**La mitad (b) no esta completa y no se afirma que lo este.** Cuando exista el
constructor de contexto, esta prueba tiene que crecer para comprobar el texto
real que sale hacia el proveedor.

POR QUE UNA PRUEBA ESTRUCTURAL Y NO UNA DE COMPORTAMIENTO
----------------------------------------------------------
Una prueba de comportamiento dice "en este caso no hubo fuga". Una prueba
estructural dice "no hay ninguna via por la que pudiera haberla". Para una
afirmacion del tipo "el modelo nunca ve una fila", la segunda es la unica que
vale: los casos son infinitos y las vias, contables.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
PAQUETE = RAIZ / "guardian"
FUENTES = sorted(PAQUETE.glob("*.py"))

# Lo unico que el guardian puede importar. Todo lo demas es una via de salida
# o una fuente de no-determinismo.
IMPORTS_PERMITIDOS = {
    "sqlglot",
    "dataclasses",
    "typing",
    "__future__",
    # los modulos del propio paquete
    "catalogo", "contrato", "nucleo", "politica",
}

# Cada uno de estos rompe una propiedad declarada del guardian.
IMPORTS_PROHIBIDOS = {
    "socket": "red", "http": "red", "urllib": "red", "requests": "red",
    "httpx": "red", "ftplib": "red", "smtplib": "red", "asyncio": "concurrencia/red",
    "psycopg": "base de datos", "sqlite3": "base de datos", "sqlalchemy": "base de datos",
    "datetime": "reloj", "time": "reloj", "calendar": "reloj",
    "random": "aleatoriedad", "secrets": "aleatoriedad", "uuid": "aleatoriedad",
    "os": "sistema de ficheros / entorno", "pathlib": "sistema de ficheros",
    "shutil": "sistema de ficheros", "io": "entrada/salida", "tempfile": "ficheros",
    "subprocess": "ejecucion", "yaml": "lectura de ficheros", "json": "serializacion de E/S",
    "logging": "salida", "pickle": "deserializacion", "importlib": "carga dinamica",
}

# Llamadas que abren una via aunque no haya `import`.
LLAMADAS_PROHIBIDAS = {"open", "eval", "exec", "compile", "__import__", "input", "print"}


def _arboles():
    for fuente in FUENTES:
        yield fuente, ast.parse(fuente.read_text(encoding="utf-8"))


def test_el_paquete_tiene_fuentes():
    """Si el paquete se vaciara, las comprobaciones de abajo pasarian sin mirar
    nada. Una prueba que puede quedarse sin objeto tiene que decirlo."""
    assert len(FUENTES) >= 4, f"solo se encontraron {len(FUENTES)} ficheros en {PAQUETE}"


@pytest.mark.parametrize("fuente", FUENTES, ids=[f.name for f in FUENTES])
def test_el_guardian_no_importa_nada_que_pueda_salir(fuente):
    arbol = ast.parse(fuente.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        modulos: list[str] = []
        if isinstance(nodo, ast.Import):
            modulos = [alias.name for alias in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            modulos = [nodo.module or ""]

        for modulo in modulos:
            raiz = modulo.lstrip(".").split(".")[0]
            if not raiz:
                continue                      # `from . import x`
            motivo = IMPORTS_PROHIBIDOS.get(raiz)
            assert motivo is None, (
                f"{fuente.name} importa `{modulo}` ({motivo}). El guardian no hace "
                f"entrada/salida, no mide el tiempo y no usa aleatoriedad: si lo "
                f"hiciera, dejaria de ser determinista y de ser auditable."
            )
            assert raiz in IMPORTS_PERMITIDOS, (
                f"{fuente.name} importa `{modulo}`, que no esta en la lista blanca "
                f"de importaciones del guardian. Si hace falta de verdad, se añade "
                f"aqui con su justificacion — no se añade en silencio."
            )


@pytest.mark.parametrize("fuente", FUENTES, ids=[f.name for f in FUENTES])
def test_el_guardian_no_llama_a_nada_que_abra_una_via(fuente):
    arbol = ast.parse(fuente.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            assert nodo.func.id not in LLAMADAS_PROHIBIDAS, (
                f"{fuente.name} llama a `{nodo.func.id}()`. Ni siquiera para depurar: "
                f"un `print` en el guardian es una salida no auditada."
            )


def test_el_catalogo_no_contiene_ni_una_fila_de_datos():
    """`catalogo.yaml` es la UNICA fuente del texto que se enviara al proveedor.

    Los centinelas son nombres improbables a proposito: si alguno apareciera en
    lo que sale del pais, la fuga seria inequivoca y no admitiria explicacion
    alternativa. Que no esten aqui es condicion necesaria, no suficiente — la
    suficiente llega con el constructor de contexto (I-4).
    """
    texto = (RAIZ / "catalogo.yaml").read_text(encoding="utf-8")
    for centinela in ("Vercingetorix", "Qhuazbal", "Ñemerov", "CENTINELA-QX7Z-4M91"):
        assert centinela not in texto, (
            f"El centinela '{centinela}' aparece en catalogo.yaml. Eso significa que "
            f"un dato de una tabla llego al texto que se envia al modelo."
        )

    # Y ademas: ningun valor del catalogo puede venir de la base. Los unicos
    # valores enumerados son los declarados a mano en §7.2.
    catalogo = yaml.safe_load(texto)
    permitidos = catalogo["valores_permitidos"]
    assert set(permitidos["consulta.unidades.torre"]) == {"A", "B", "C"}
    assert set(permitidos["consulta.cuotas.estado"]) == {"pagada", "vencida", "corriente"}


def _cadenas_de_codigo(arbol: ast.AST) -> list[str]:
    """Literales de texto del CODIGO, excluidos los docstrings.

    La primera version de esta prueba miraba el fichero entero como texto y
    fallo por un COMENTARIO que citaba `'cartera.propietarios'::regclass` al
    explicar M-19. El comentario tenia que estar ahi: es la explicacion de por
    que S7a existe. Un comentario no puede leer un fichero ni abrir una
    conexion; un literal de codigo si puede acabar en una ruta o en una
    consulta. La prueba se corrigio para mirar lo que puede hacer algo, no lo
    que puede leerse.
    """
    docstrings = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            cuerpo = getattr(nodo, "body", [])
            if (
                cuerpo
                and isinstance(cuerpo[0], ast.Expr)
                and isinstance(cuerpo[0].value, ast.Constant)
                and isinstance(cuerpo[0].value.value, str)
            ):
                docstrings.add(id(cuerpo[0].value))
    return [
        nodo.value
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Constant)
        and isinstance(nodo.value, str)
        and id(nodo) not in docstrings
    ]


@pytest.mark.parametrize("fuente", FUENTES, ids=[f.name for f in FUENTES])
def test_el_volcado_de_datos_no_esta_al_alcance_del_guardian(fuente):
    """El guardian no conoce la existencia de los datos ni de la conexion.

    No basta con que no importe `pathlib`: tampoco puede llevar escrita una
    ruta, un nombre de tabla base ni una cadena de conexion, porque eso seria
    la mitad de una via de salida esperando a la otra mitad.
    """
    arbol = ast.parse(fuente.read_text(encoding="utf-8"))
    for cadena in _cadenas_de_codigo(arbol):
        for rastro in ("04-datos.sql", "cartera.", "DATABASE_URL", "postgresql://",
                       "consulta_ro", ".sql\"", "/datos"):
            assert rastro not in cadena, (
                f"{fuente.name} contiene el literal {cadena!r}, que menciona "
                f"'{rastro}'. El guardian no tiene ningun motivo para conocer los "
                f"datos, su ubicacion ni la credencial."
            )
