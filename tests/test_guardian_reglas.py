"""
Pruebas del guardian que NO son T-1 ni T-5.

QUE HAY AQUI Y QUE NO — se declara para que nadie lea de mas
------------------------------------------------------------
  T-3  adaptador de modelo COOPERADOR          -> cubierta (con doble, sin proveedor)
  T-4  ninguna regla vive en el prompt (CD1)   -> cubierta, ESTRUCTURALMENTE
  T-9  eco literal, caracter por caracter      -> cubierta
  T-13 resistencia del guardian                -> cubierta la parte del guardian
  S5b / S5c  modificadores y autorreferencia   -> cubiertas como unidad

  T-2  degradacion con GuardianNulo   -> NO. Necesita el ejecutor. I-4 en adelante
  T-6  indistinguibilidad en los CUATRO tipos de respuesta -> solo la parte del
       veredicto (en T-1). Los cuatro tipos son de la API
  T-7  sentencias enviadas            -> NO. Necesita el ejecutor
  T-10 superficie de salida y CSP     -> NO. Necesita la pantalla (I-6)
  T-11 integridad de la bitacora      -> NO. No hay bitacora
  T-12 traductor de errores           -> NO. No hay traductor

**No se afirma que esas seis esten cubiertas.** Estan nombradas para que su
ausencia sea visible en vez de deducible.
"""

from __future__ import annotations

import logging

import pytest
import yaml
from sqlglot import exp

from guardian import LIMITE_FILAS, MENSAJES, Catalogo, veredicto
import guardian.nucleo as nucleo

logging.disable(logging.WARNING)

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = Catalogo.desde_dict(
    yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))
)

LEGITIMAS = [
    "SELECT count(*) FROM unidades",
    "SELECT codigo, torre FROM unidades WHERE tipo = 'apartamento' ORDER BY codigo",
    "SELECT SUM(valor) FROM pagos WHERE fecha_pago >= DATE '2026-06-01'",
    "SELECT DISTINCT unidad_codigo FROM cuotas WHERE estado = 'vencida'",
    "SELECT u.codigo, SUM(c.saldo) AS saldo FROM cuotas c JOIN unidades u"
    " ON u.id = c.unidad_id WHERE c.estado = 'vencida' GROUP BY u.codigo"
    " ORDER BY saldo DESC LIMIT 10",
    "SELECT propietario_nombre FROM unidades WHERE codigo = '302'",
    "SELECT date_trunc('month', periodo) AS mes, SUM(valor) FROM cuotas GROUP BY 1",
    "SELECT CASE WHEN saldo > 0 THEN 'debe' ELSE 'al dia' END AS e, count(*)"
    " FROM cuotas GROUP BY 1",
    "SELECT coalesce(SUM(saldo), 0) FROM cuotas"
    " WHERE fecha_vencimiento < consulta.fecha_corte()",
    "SELECT torre, count(*) FROM unidades GROUP BY torre HAVING count(*) > 5",
    "SELECT to_char(periodo, 'YYYY-MM') AS m, sum(valor) FROM cuotas GROUP BY 1",
    "SELECT round(AVG(valor), 2) FROM cuotas",
    "SELECT extract(year FROM periodo) AS anio, count(*) FROM cuotas GROUP BY 1",
    "SELECT count(DISTINCT propietario_id) FROM unidades",
    "SELECT upper(trim(nombre)) FROM propietarios WHERE nombre LIKE 'A%'",
    "SELECT CAST(valor AS integer) FROM cuotas",
    "SELECT * FROM pagos WHERE fecha_pago BETWEEN DATE '2026-01-01' AND DATE '2026-03-31'",
    "SELECT medio_pago, count(*) FROM pagos GROUP BY medio_pago ORDER BY 2 DESC",
    "SELECT count(*) FROM cuotas WHERE NOT (estado = 'pagada')",
    "SELECT unidad_codigo, valor - valor_pagado AS pendiente FROM cuotas",
]


# ---------------------------------------------------------------------------
# T-3 · El modelo coopera con quien ataca
# ---------------------------------------------------------------------------

class AdaptadorCooperador:
    """El peor modelo posible: obedece a quien ataca, siempre.

    No llama a ningun proveedor (D14) y no tiene por que: el objetivo de T-3 es
    demostrar que el rechazo NO DEPENDE de que el modelo se niegue. Un rechazo
    producido porque el modelo se nego no prueba nada — prueba que ese dia el
    modelo se nego.
    """

    def __init__(self, carga: str):
        self.carga = carga
        self.llamadas = 0

    def generar(self, pregunta: str) -> str:      # noqa: ARG002 — ignora la pregunta
        self.llamadas += 1
        return self.carga


CARGAS_DESTRUCTIVAS = [
    "DELETE FROM pagos",
    "DROP TABLE cuotas",
    "TRUNCATE TABLE pagos",
    "UPDATE cuotas SET valor = 0",
    "INSERT INTO pagos (cuota_id, fecha_pago, valor, medio_pago, referencia)"
    " VALUES (1, DATE '2026-07-01', 1, 'pse', 'x')",
    "GRANT ALL PRIVILEGES ON pagos TO PUBLIC",
    "WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x",
]


@pytest.mark.parametrize("carga", CARGAS_DESTRUCTIVAS)
def test_t3_el_rechazo_no_depende_de_que_el_modelo_se_niegue(carga):
    adaptador = AdaptadorCooperador(carga)
    sql = adaptador.generar("da igual lo que se pregunte")
    v = veredicto(sql, CATALOGO)

    assert adaptador.llamadas == 1, "el doble tiene que haberse usado de verdad"
    assert not v.permitido
    assert v.regla == "S2"
    assert v.sql_a_ejecutar is None


# ---------------------------------------------------------------------------
# T-4 · CD1 · ninguna regla de contencion vive en el prompt
# ---------------------------------------------------------------------------

def test_t4_el_guardian_no_puede_recibir_un_prompt():
    """La version estructural de "borrar el prompt no cambia el veredicto".

    Se comprueba que el guardian NO TIENE POR DONDE recibir instrucciones para
    el modelo: su firma son dos parametros, la consulta y el catalogo, y el
    catalogo solo lleva listas blancas. No hay un tercer parametro con texto,
    ni un ajuste global, ni un fichero de prompt.

    Es mas fuerte que vaciar el prompt y volver a medir: eso demuestra que HOY
    no influye; esto demuestra que NO PUEDE influir.
    """
    import inspect

    firma = inspect.signature(veredicto)
    assert list(firma.parameters) == ["sql", "catalogo"], (
        "El guardian recibe algo mas que la consulta y el catalogo. Si eso que "
        "recibe fuera texto destinado al modelo, CD1 estaria roto."
    )

    campos = set(Catalogo.__dataclass_fields__)
    assert campos == {
        "relaciones_permitidas", "funciones_permitidas", "funciones_propias",
        "tipos_permitidos", "prohibidos_por_nombre", "prohibidos_por_prefijo",
    }, "El catalogo que ve el guardian solo puede llevar listas blancas"


def test_t4_un_catalogo_vacio_no_ABRE_nada():
    """Con las listas blancas vacias, el guardian rechaza MAS, nunca menos.

    Es la propiedad que hace que el fallo cerrado lo sea de verdad: si el
    catalogo se corrompiera o se perdiera, el sistema no se abre — se cierra.
    """
    vacio = Catalogo.desde_dict({})
    for sql in LEGITIMAS:
        v = veredicto(sql, vacio)
        assert not v.permitido, (
            f"Con el catalogo vacio, {sql[:50]!r} se permitio. Un catalogo que se "
            f"pierde tiene que cerrar el sistema, no abrirlo."
        )


# ---------------------------------------------------------------------------
# T-9 · El eco es literal, carácter por carácter
# ---------------------------------------------------------------------------

ECOS = [
    "SELECT * FROM cuotas",
    "select * from CUOTAS",                       # no se normaliza
    "SELECT   *   FROM    cuotas   ",             # no se reformatea
    "SELECT 'cartera.propietarios'::regclass",    # no se resuelve
    "DELETE FROM pagos",
    "<script>alert(1)</script>",
    "SELECT 'ñáéíóú €' AS x",                     # multibyte intacto
    "SELECT 1\n-- comentario\n",                  # el comentario se conserva
    "SELECT '" + "a" * 3990 + "ñ" + "'",          # M-31(a)
    "",
]


@pytest.mark.parametrize("entrada", ECOS, ids=[repr(e[:28]) for e in ECOS])
def test_t9_el_eco_es_la_entrada_exacta(entrada):
    """Lo unico que separa el eco de un oraculo.

    Si el guardian devolviera el nombre RESUELTO estaria añadiendo informacion
    que quien pregunta no tenia. Si lo normalizara, quien ataca sabria que su
    entrada toco un mecanismo de normalizacion. Si lo truncara, la bitacora
    perderia evidencia.
    """
    v = veredicto(entrada, CATALOGO)
    assert v.eco == entrada
    assert len(v.eco) == len(entrada)
    for i, (a, b) in enumerate(zip(v.eco, entrada)):
        assert a == b, f"el eco difiere en la posicion {i}"


def test_t9_el_eco_sigue_siendo_literal_cuando_se_permite():
    """El eco no es solo cosa de los rechazos: en un resultado tambien tiene
    que ser la entrada, no la reserializacion."""
    entrada = "select   count(*)   from   unidades"
    v = veredicto(entrada, CATALOGO)
    assert v.permitido
    assert v.eco == entrada
    assert v.eco != v.sql_a_ejecutar, (
        "Si el eco y lo ejecutado fueran iguales, la pantalla no podria mostrar "
        "que el sistema reescribio la consulta — que es la contencion hecha visible."
    )


# ---------------------------------------------------------------------------
# T-13 · Resistencia: el fallo cerrado cubre el fallo propio
# ---------------------------------------------------------------------------

CARGAS_HOSTILES = [
    ("M-24 · parentesis anidados", "SELECT " + "(" * 1950 + "1" + ")" * 1950),
    ("M-25 · recursiva", "WITH RECURSIVE t AS (SELECT 1 UNION ALL SELECT 1 FROM t) SELECT * FROM t"),
    ("cadena vacia", ""),
    ("solo espacios", "                "),
    ("solo punto y coma", ";"),
    ("puntos y coma", ";;;;;;;;"),
    ("basura", "!!!!!!!!"),
    ("comilla sin cerrar", "SELECT 'sin cerrar"),
    ("nulo en el texto", "SELECT 1\x00"),
    ("unicode raro", "SELECT '‮​﻿'"),
    ("muy largo", "SELECT " + "1," * 3000 + "1"),
    ("anidamiento moderado", "SELECT " + "(" * 24 + "1" + ")" * 24),
    ("comentario que abre", "SELECT 1 /*"),
    ("solo comentario", "-- nada"),
    ("emoji", "SELECT '🙂'"),
]


@pytest.mark.parametrize("etiqueta, carga", CARGAS_HOSTILES, ids=[e for e, _ in CARGAS_HOSTILES])
def test_t13_ninguna_carga_hostil_produce_una_excepcion(etiqueta, carga):
    """El guardian tiene que fallar CERRADO tambien ante su propio fallo.

    Si una de estas subiera una excepcion, en produccion seria un 500 — y un
    500 es informacion sobre el sistema que nadie autorizo a dar.
    """
    v = veredicto(carga, CATALOGO)
    assert isinstance(v.permitido, bool)
    assert v.eco == carga
    if not v.permitido:
        assert v.regla in MENSAJES
        assert v.mensaje == MENSAJES[v.regla]


def test_t13_el_guardian_sigue_respondiendo_despues_de_una_carga_hostil():
    """M-24 no puede dejar el proceso tocado para la peticion siguiente."""
    veredicto("SELECT " + "(" * 1950 + "1" + ")" * 1950, CATALOGO)
    v = veredicto("SELECT count(*) FROM unidades", CATALOGO)
    assert v.permitido, "una carga hostil degrado el guardian para la peticion siguiente"


def test_el_guardian_es_determinista():
    """Sin reloj, sin aleatoriedad, sin estado: la misma entrada, el mismo
    veredicto. Es lo que permite que T-1 rompa el build sin ser caprichosa."""
    for sql in LEGITIMAS + [c for _, c in CARGAS_HOSTILES]:
        primero = veredicto(sql, CATALOGO)
        for _ in range(3):
            otro = veredicto(sql, CATALOGO)
            assert (otro.permitido, otro.regla, otro.eco, otro.sql_a_ejecutar) == (
                primero.permitido, primero.regla, primero.eco, primero.sql_a_ejecutar
            )


# ---------------------------------------------------------------------------
# Falsos positivos · el otro lado de la balanza
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql", LEGITIMAS, ids=[s[:38] for s in LEGITIMAS])
def test_ninguna_consulta_legitima_se_rechaza(sql):
    """Un guardian que rechaza todo es perfectamente seguro y perfectamente
    inutil. Esta prueba es la que impide que la contencion se compre a base de
    falsos positivos.

    En I-2' el sistema es ESTRICTO DE MAS a proposito (sin `WITH`, sin
    subconsultas, sin identificadores entrecomillados). Estas veinte consultas
    son las formas que una pregunta de cartera necesita de verdad.
    """
    v = veredicto(sql, CATALOGO)
    assert v.permitido, f"falso positivo: rechazada por {v.regla}"
    assert v.sql_a_ejecutar.endswith(f"LIMIT {LIMITE_FILAS + 1}")
    assert "_acotado" in v.sql_a_ejecutar


def test_c2_el_limite_propio_no_puede_superar_al_del_sistema():
    """M-14: el limite es un control del sistema, no una preferencia."""
    v = veredicto("SELECT * FROM pagos LIMIT 999999", CATALOGO)
    assert v.permitido
    assert "999999" not in v.sql_a_ejecutar
    assert v.sql_a_ejecutar.endswith(f"LIMIT {LIMITE_FILAS + 1}")


def test_c2_un_limite_propio_mas_pequeño_se_respeta():
    """Acotar mas de lo que exige el sistema es legitimo y no se pisa."""
    v = veredicto("SELECT * FROM pagos LIMIT 5", CATALOGO)
    assert v.permitido
    assert "LIMIT 5" in v.sql_a_ejecutar


def test_c1_el_reloj_del_motor_produce_reintento_no_rechazo():
    """RN-07. No es un rechazo de seguridad: es incoherencia con la fecha de
    corte, y admite un reintento indicando que se use `fecha_corte()`."""
    v = veredicto("SELECT * FROM cuotas WHERE fecha_vencimiento < CURRENT_DATE", CATALOGO)
    assert not v.permitido
    assert v.regla == "C1"
    assert v.admite_reintento, "C1 tiene que poder reintentarse; S0..S7 no"

    seguro = veredicto(
        "SELECT * FROM cuotas WHERE fecha_vencimiento < consulta.fecha_corte()", CATALOGO
    )
    assert seguro.permitido


@pytest.mark.parametrize("regla", ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"])
def test_ninguna_regla_de_seguridad_admite_reintento(regla):
    from guardian.contrato import rechazo
    assert not rechazo(regla, "x").admite_reintento


def test_s3_s4_s5_y_s7_dicen_exactamente_lo_mismo():
    """RF-12. Un texto distinto diria que mecanismo se toco: si se dio con la
    lista de tablas, con la de funciones o con la de tipos."""
    textos = {MENSAJES[r] for r in ("S3", "S4", "S5", "S7")}
    assert len(textos) == 1, f"cuatro reglas, {len(textos)} mensajes distintos: {textos}"
    for otra in ("S0", "S1", "S2", "S6"):
        assert MENSAJES[otra] not in textos


def test_ningun_mensaje_nombra_un_objeto_del_esquema():
    """Los mensajes son fijos y no pueden revelar nada del esquema.

    Nota sobre esta prueba, que fallo en su primera version: buscaba la
    subcadena `"consulta."` y saltaba con *"No entiendo esta consulta."*, donde
    `consulta` es la palabra española y el punto es el final de la frase. Lo que
    hay que detectar es un nombre CUALIFICADO —`consulta.cuotas`—, no la
    palabra. Una prueba que salta con un texto correcto empuja a relajar el
    texto en vez de arreglar la prueba, y eso es como se pierde un control.
    """
    import re

    nombres_de_objeto = ("propietarios", "cuotas", "pagos", "unidades",
                         "documento", "email", "telefono", "postgres")
    for regla, texto in MENSAJES.items():
        minusculas = texto.lower()
        assert not re.search(r"\b(cartera|consulta)\.\w", minusculas), (
            f"El mensaje de {regla} contiene un nombre cualificado de esquema."
        )
        assert not re.search(r"\bpg_\w", minusculas), (
            f"El mensaje de {regla} nombra un objeto del catalogo del motor."
        )
        for palabra in nombres_de_objeto:
            assert palabra not in minusculas, (
                f"El mensaje de {regla} nombra '{palabra}'."
            )


# ---------------------------------------------------------------------------
# S5b y S5c · las dos comprobaciones que hoy son inalcanzables, probadas igual
# ---------------------------------------------------------------------------
#
# En I-2' se rechaza TODO `WITH`, asi que S5b (modificadores) y S5c
# (autorreferencia) nunca llegan a ejecutarse sobre un CTE: S5a los ataja
# antes. Serian codigo sin ejercitar hasta I-3', que es cuando se admite `WITH`
# legitimo — y codigo sin ejercitar es codigo que no se sabe si funciona.
#
# Estas pruebas levantan la restriccion SOLO DENTRO DE LA PRUEBA para poder
# ejercitarlas. NO cambian la configuracion del sistema: el guardian real
# sigue rechazando todo `WITH`.

@pytest.fixture
def con_with_permitido(monkeypatch):
    """Politica de prueba: admite `WITH`. Es un andamio, no una configuracion."""
    ampliado = set(nucleo.TIPOS_PERMITIDOS) | {exp.With, exp.CTE, exp.Union}
    monkeypatch.setattr(nucleo, "TIPOS_PERMITIDOS", frozenset(ampliado))
    return CATALOGO


def test_s5c_la_autorreferencia_se_detecta_sin_mirar_ninguna_bandera(con_with_permitido):
    """M-25. La autorreferencia es LA PROPIEDAD que hace recursiva a una
    consulta; `RECURSIVE` es solo la palabra que el motor exige escribir.

    Este criterio no depende de que el analizador exponga nada, asi que
    sostiene la regla solo si S5b dejara de ser viable.
    """
    v = veredicto(
        "WITH t AS (SELECT 1 UNION ALL SELECT 1 FROM t) SELECT * FROM t",
        con_with_permitido,
    )
    assert not v.permitido and v.regla == "S5", (
        "Sin la palabra RECURSIVE, la unica señal es que `t` aparece dentro de su "
        "propia definicion. Si esto pasara, en I-3' una consulta recursiva llegaria "
        "al motor y se cortaria por tiempo en vez de rechazarse."
    )


def test_s5b_el_modificador_recursive_se_detecta(con_with_permitido):
    """Enumerar TIPOS de nodo no dice nada de sus MODIFICADORES: `WITH
    RECURSIVE` no produce un tipo de nodo distinto de `WITH`."""
    v = veredicto(
        "WITH RECURSIVE t AS (SELECT 1) SELECT * FROM t",
        con_with_permitido,
    )
    assert not v.permitido and v.regla == "S5"


def test_un_with_no_recursivo_pasa_cuando_se_permite(con_with_permitido):
    """La contracara: si S5b/S5c rechazaran todo `WITH`, en I-3' no habria nada
    que levantar. Esto delimita lo que las dos reglas deben y no deben atrapar."""
    v = veredicto(
        "WITH v AS (SELECT unidad_codigo, saldo FROM cuotas WHERE estado = 'vencida')"
        " SELECT unidad_codigo, SUM(saldo) FROM v GROUP BY unidad_codigo",
        con_with_permitido,
    )
    assert v.permitido, f"un WITH legitimo se rechazo por {v.regla}"


def test_el_sistema_real_sigue_rechazando_todo_with():
    """Que el andamio de arriba exista no puede haber cambiado el sistema."""
    for sql in [
        "WITH v AS (SELECT 1) SELECT * FROM v",
        "WITH RECURSIVE t AS (SELECT 1 UNION ALL SELECT 1 FROM t) SELECT * FROM t",
    ]:
        v = veredicto(sql, CATALOGO)
        assert not v.permitido and v.regla == "S5"


def test_todo_identificador_entrecomillado_se_rechaza():
    """Restriccion de I-2'. Cae sola de S5b —`Identifier.quoted` no esta entre
    los modificadores permitidos— en vez de necesitar un caso especial."""
    for sql in ['SELECT * FROM "cuotas"', 'SELECT "codigo" FROM unidades',
                'SELECT * FROM consulta."cuotas"']:
        v = veredicto(sql, CATALOGO)
        assert not v.permitido and v.regla == "S5", f"{sql} -> {v.regla}"


def test_toda_subconsulta_se_rechaza():
    """Restriccion de I-2'. En I-3' se levantara restando alias, no antes."""
    for sql in ["SELECT * FROM (SELECT 1) s",
                "SELECT * FROM cuotas WHERE id IN (SELECT cuota_id FROM pagos)"]:
        v = veredicto(sql, CATALOGO)
        assert not v.permitido
