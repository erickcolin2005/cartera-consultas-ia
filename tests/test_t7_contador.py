"""
T-7 · `sentencias_enviadas` es un hecho medido, no una frase.

ROMPE EL BUILD.

QUE AFIRMA LA PANTALLA, Y POR QUE HAY QUE PROBARLO ASI
-------------------------------------------------------
En un rechazo, la pantalla escribe:

    Sentencias enviadas a la base de datos: 0

Ese cero es la cifra mas visible del proyecto. Y una prueba que solo afirmara
«en un rechazo el contador vale 0» la pasaria con nota **un contador averiado
que devolviera siempre 0**. No distinguiria «no se envio nada» de «el
instrumento no funciona», que es exactamente el defecto que este proyecto
denuncia en las tablas de resultados que solo publican aciertos.

Por eso T-7 tiene CUATRO partes, y las cuatro estan aqui:

  (a) CASO POSITIVO — en M-13 y M-14, que el guardian permite y por tanto SI
      se ejecutan, el contador tiene que SUBIR. Es la mitad que convierte la
      prueba en una medicion.
  (b) EL CONTADOR EN EL BORDE — envolviendo el cursor y contando envios de
      sentencia, no llamadas al ejecutor. Si viviera en `ejecutar`, la prueba
      solo diria «no llamamos al ejecutor», que es tautologico con leer el
      flujo de control. Y NUNCA propiedad del cursor: en un rechazo no se crea
      cursor, asi que un contador del cursor daria cero por no existir jamas.
  (c) TESTIGO DEL LADO DEL SERVIDOR — el motor mismo dice cuantas sentencias
      recibio. Un testigo que viviera en nuestro proceso y con nuestro rol no
      seria un testigo: seria la misma afirmacion escrita dos veces.
  (d) RUIDO ACOTADO — sin pool y sin reconexion, de modo que «no llego ninguna
      sentencia» significa lo que un lector entiende.

COMO SE CONSIGUE EL TESTIGO, Y QUE SE DESCARTO ANTES
------------------------------------------------------
El modelo de amenazas propuso `pg_stat_database` y dejo anotado que **no habia
verificado** si distingue una sentencia de una transaccion. Se midio: no lo
hace. Tres sentencias en autocommit movieron el contador SEIS, porque
`pg_stat_database` cuenta transacciones **de toda la base** e incluye las del
propio testigo al leerse. Servia para una tendencia, no para una asercion.

Lo que si sirve es el registro del motor, activado **solo para el rol de la
aplicacion**:

    ALTER ROLE consulta_ro SET log_statement = 'all'

Tres propiedades lo hacen buen testigo:

  1. Lo escribe PostgreSQL, no nosotros, y desde fuera de nuestro proceso.
  2. Va por rol, asi que las sentencias del dueño —incluidas las del propio
     testigo— no ensucian el recuento. La parte (d) sale de aqui.
  3. **`consulta_ro` no puede apagarlo.** Se comprobo: cambiar `log_statement`
     pide superusuario y el rol de la aplicacion no lo es. Un testigo que el
     observado pudiera silenciar no seria un testigo.

El ajuste se pone y se quita en el fixture. NO vive en el esquema a proposito:
dejarlo permanente escribiria el texto literal de cada visitante en el
registro del contenedor, que es una segunda copia del problema de retencion
que la bitacora ya tiene acotado.

ESTA PRUEBA NECESITA DOCKER, Y NO SE SALTA
-------------------------------------------
Lee el registro del contenedor con `docker compose logs`. Si no hay docker,
FALLA — no se salta. Es el mismo criterio que `conftest.py` aplica a T-8: una
prueba de seguridad que se salta sola cuando no encuentra su entorno es una
prueba que un dia deja de correr sin que nadie se entere.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.ejecutor import Contador, _CursorContado, ejecutar  # noqa: E402
from guardian.catalogo import Catalogo  # noqa: E402
from guardian.contrato import LIMITE_FILAS  # noqa: E402
from guardian.nucleo import veredicto  # noqa: E402

CATALOGO = Catalogo.desde_dict(
    yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))
)

MARCA_SENTENCIA = "LOG:  statement:"

# El driver abre y cierra transaccion por su cuenta. Esas dos NO pasan por
# nuestro envoltorio del cursor, asi que nuestro contador no las ve — y no es
# un fallo del contador: cuenta las sentencias que ENVIA la aplicacion, no las
# que el driver añade para gestionar la transaccion.
#
# Se midio: una consulta ejecutada deja TRES lineas en el registro del motor
# (`BEGIN`, la consulta, `COMMIT`) y nuestro contador marca 1.
#
# La distincion importa en las dos direcciones:
#   - Para el caso positivo hay que contar solo consultas, o el numero del
#     motor y el nuestro no serian comparables nunca.
#   - Para el rechazo hay que contarlo TODO, incluido `BEGIN`: ahi la
#     afirmacion fuerte es que el motor no recibio absolutamente nada, y un
#     `BEGIN` suelto ya seria una conexion abierta que la pantalla niega.
CONTROL_DE_TRANSACCION = ("BEGIN", "COMMIT", "ROLLBACK")


# ---------------------------------------------------------------------------
# El testigo del lado del servidor
# ---------------------------------------------------------------------------


class Testigo:
    """Lo que el MOTOR dice haber recibido del rol de la aplicacion.

    Cuenta sobre el registro completo y por diferencia, no por ventana de
    tiempo: una ventana temporal falla sola el dia que la maquina va lenta, y
    un fallo intermitente en una prueba de seguridad acaba en `skip`.
    """

    # El nombre empieza por «Test» y pytest intentaria recogerla como suite.
    # Se le dice que no lo es, en vez de renombrarla: el nombre es el del
    # concepto del diseño y vale mas que evitar una linea.
    __test__ = False

    def __init__(self) -> None:
        self.base_consultas, self.base_todo = self._anotadas()

    @staticmethod
    def _anotadas() -> tuple[int, int]:
        """Devuelve (consultas, todo). Ver `CONTROL_DE_TRANSACCION`."""
        try:
            salida = subprocess.run(
                ["docker", "compose", "logs", "db", "--no-log-prefix"],
                cwd=RAIZ,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            pytest.fail(
                f"T-7(c) no pudo leer el registro del motor ({e}). Esta prueba "
                f"necesita docker y NO se salta: sin testigo externo, el "
                f"contador solo se afirma a si mismo."
            )
        if salida.returncode != 0:
            pytest.fail(
                f"`docker compose logs db` fallo:\n{salida.stderr[:400]}"
            )

        todo = consultas = 0
        for linea in salida.stdout.splitlines():
            posicion = linea.find(MARCA_SENTENCIA)
            if posicion < 0:
                continue
            todo += 1
            enviado = linea[posicion + len(MARCA_SENTENCIA):].strip()
            if enviado.upper().rstrip(";") not in CONTROL_DE_TRANSACCION:
                consultas += 1
        return consultas, todo

    def consultas(self) -> int:
        """Sentencias que envio la aplicacion, sin el control de transaccion."""
        return self._anotadas()[0] - self.base_consultas

    def todo(self) -> int:
        """TODO lo que el motor recibio de ese rol, `BEGIN` incluido."""
        return self._anotadas()[1] - self.base_todo


@pytest.fixture
def testigo(conexion_owner):
    """Enciende el registro para `consulta_ro` y lo apaga pase lo que pase.

    Se usa `conexion_owner` a proposito: encender el testigo requiere un rol
    que el observado no tiene. Esa asimetria es lo que lo hace un testigo.
    """
    conexion_owner.execute("ALTER ROLE consulta_ro SET log_statement = 'all'")
    try:
        # El ajuste entra en la PROXIMA conexion. El ejecutor abre una nueva
        # por consulta (ADR-15), asi que no hay nada que reciclar.
        yield Testigo()
    finally:
        conexion_owner.execute("ALTER ROLE consulta_ro RESET log_statement")


# ---------------------------------------------------------------------------
# (a) CASO POSITIVO — la mitad sin la cual esto no es una medicion
# ---------------------------------------------------------------------------

CONSULTAS_QUE_SI_EJECUTAN = [
    # M-13 del banco: producto cartesiano. El guardian NO lo rechaza; la
    # contencion es declarada (limite de filas + tiempo maximo). Ejecuta.
    ("M-13", "SELECT * FROM pagos, cuotas, unidades, propietarios"),
    # M-14: el equivalente SQL de «dame todo sin limite». El guardian lo
    # permite y le impone SU limite al reserializar.
    ("M-14", "SELECT * FROM pagos LIMIT 999999"),
    ("normal-1", "SELECT unidad_codigo, saldo FROM cuotas WHERE saldo > 0"),
    ("normal-2", "SELECT estado, COUNT(*) AS n FROM cuotas GROUP BY estado"),
    ("normal-3", "SELECT medio_pago, SUM(valor) AS t FROM pagos GROUP BY medio_pago"),
]


@pytest.mark.parametrize(
    "caso,sql", CONSULTAS_QUE_SI_EJECUTAN, ids=[c for c, _ in CONSULTAS_QUE_SI_EJECUTAN]
)
def test_a_el_contador_SUBE_en_las_consultas_que_si_se_ejecutan(caso, sql):
    """Sin esto, un contador clavado en cero pasaria T-7 entera."""
    v = veredicto(sql, CATALOGO)
    assert v.permitido, f"{caso} deberia pasar el guardian; salio por {v.regla}"

    r = ejecutar(v)
    assert r.error is None, f"{caso} fallo en el motor: {r.error}"
    assert r.sentencias_enviadas == 1, (
        f"{caso} se ejecuto de verdad y el contador marca "
        f"{r.sentencias_enviadas}. Si marca 0, el instrumento esta averiado y "
        f"el 0 de la pantalla no significa nada."
    )


def test_a_m13_y_m14_quedan_contenidos_por_el_limite_de_filas():
    """El caso positivo no puede pagarse aflojando la contencion.

    M-13 y M-14 SE EJECUTAN — por eso sirven de caso positivo— y aun asi
    tienen que salir acotados. Si esta prueba cayera, el contador subiria
    porque el sistema dejo de contener, no porque mida bien.
    """
    for caso, sql in [
        ("M-13", "SELECT * FROM pagos, cuotas, unidades, propietarios"),
        ("M-14", "SELECT * FROM pagos LIMIT 999999"),
    ]:
        r = ejecutar(veredicto(sql, CATALOGO))
        assert len(r.filas) <= LIMITE_FILAS, (
            f"{caso} devolvio {len(r.filas)} filas: la contencion declarada "
            f"del limite de filas no se aplico."
        )


@pytest.mark.parametrize(
    "caso,sql",
    [
        ("M-01", "DELETE FROM pagos WHERE fecha_pago > '2026-01-01'"),
        ("M-09", "WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x"),
        ("truncado", "TRUNCATE TABLE cuotas"),
        ("fuera-de-alcance", "SELECT * FROM cartera.propietarios"),
        ("apagar-solo-lectura",
         "SELECT set_config('default_transaction_read_only','off',false)"),
    ],
)
def test_a_el_contador_es_CERO_en_los_rechazos(caso, sql):
    """La otra mitad. Vale porque la de arriba demuestra que sabe subir."""
    v = veredicto(sql, CATALOGO)
    assert not v.permitido, f"{caso} deberia ser rechazado y paso"
    assert ejecutar(v).sentencias_enviadas == 0


# ---------------------------------------------------------------------------
# (b) EL CONTADOR EN EL BORDE
# ---------------------------------------------------------------------------


def _incrementos_del_contador(arbol: ast.Module) -> list[tuple[str, str]]:
    """Devuelve (clase, funcion) de cada `sentencias_enviadas += ...`.

    LA ATRIBUCION SE HACE DESCENDIENDO, NO CON UN RECORRIDO PLANO
    -------------------------------------------------------------
    La version obvia —`ast.walk` sobre todo el modulo llevando el nombre de la
    ultima clase vista— cuenta cada metodo DOS veces: una atribuida a su clase
    y otra al modulo, porque `walk` visita tambien el `Module` y desde ahi
    alcanza todos los metodos.

    Es literalmente el mismo error que el guardian tuvo con las reglas: un
    unico recorrido atribuye al primer NODO que encaja, no al dueño real
    (ADR-20). Aqui se resuelve igual — bajando por la estructura en vez de
    aplanarla.
    """
    encontrados: list[tuple[str, str]] = []

    def funciones_de(cuerpo, clase: str) -> None:
        for nodo in cuerpo:
            if isinstance(nodo, ast.ClassDef):
                funciones_de(nodo.body, nodo.name)
            elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for interno in ast.walk(nodo):
                    if (
                        isinstance(interno, ast.AugAssign)
                        and isinstance(interno.target, ast.Attribute)
                        and interno.target.attr == "sentencias_enviadas"
                    ):
                        encontrados.append((clase, nodo.name))

    funciones_de(arbol.body, "")
    return encontrados


def test_b_el_contador_solo_se_incrementa_dentro_del_envoltorio_del_cursor():
    """Estructural. Donde vive el contador decide si mide algo.

    Si `ejecutar` incrementara el contador, la prueba de arriba solo diria
    «el codigo que decidimos ejecutar se ejecuto»: tautologico. Contando en el
    envoltorio del cursor se cuenta lo que de verdad SALE hacia el motor,
    incluido lo que envie cualquier codigo futuro que use ese mismo cursor.
    """
    arbol = ast.parse((RAIZ / "app" / "ejecutor.py").read_text(encoding="utf-8"))
    sitios = _incrementos_del_contador(arbol)

    assert sitios, "Nadie incrementa `sentencias_enviadas`. El contador es decorativo."
    for clase, funcion in sitios:
        assert (clase, funcion) == ("_CursorContado", "execute"), (
            f"`sentencias_enviadas` se incrementa en {clase or '<modulo>'}."
            f"{funcion}. Solo puede hacerlo el envoltorio del cursor, al enviar."
        )


def test_b_el_contador_NO_es_propiedad_del_cursor():
    """Dos cursores, UN contador: tiene que sumar 2.

    Si el contador fuera propiedad del cursor, en un rechazo daria cero por no
    existir nunca — un cero vacio, indistinguible del cero bueno. Este caso lo
    fija sin necesidad de base de datos.
    """

    class CursorFalso:
        def execute(self, consulta, parametros=None):
            return None

    contador = Contador()
    _CursorContado(CursorFalso(), contador).execute("SELECT 1")
    _CursorContado(CursorFalso(), contador).execute("SELECT 2")

    assert contador.sentencias_enviadas == 2, (
        "El contador no acumulo entre cursores: es del cursor y no de la "
        "peticion."
    )


def test_b_el_envoltorio_cuenta_CADA_envio_no_cada_llamada_al_ejecutor():
    """Tres envios por el mismo cursor -> 3. El contador cuenta sentencias."""

    class CursorFalso:
        def execute(self, consulta, parametros=None):
            return None

    contador = Contador()
    cursor = _CursorContado(CursorFalso(), contador)
    for _ in range(3):
        cursor.execute("SELECT 1")

    assert contador.sentencias_enviadas == 3


def test_b_el_envoltorio_delega_todo_lo_demas_sin_tocarlo():
    """Si no delegara, alguien lo sustituiria por el cursor crudo y el
    contador dejaria de estar en el camino."""

    class CursorFalso:
        description = [("col",)]

        def fetchall(self):
            return [(1,)]

    cursor = _CursorContado(CursorFalso(), Contador())
    assert cursor.fetchall() == [(1,)]
    assert cursor.description == [("col",)]


# ---------------------------------------------------------------------------
# (c) TESTIGO DEL LADO DEL SERVIDOR
# ---------------------------------------------------------------------------


def test_c_el_motor_confirma_UNA_sentencia_cuando_la_consulta_se_ejecuta(testigo):
    """Las dos mitades tienen que coincidir: la nuestra y la del motor."""
    r = ejecutar(veredicto("SELECT estado FROM cuotas LIMIT 5", CATALOGO))

    assert r.sentencias_enviadas == 1
    assert testigo.consultas() == 1, (
        f"Nuestro contador dice 1 y el motor anoto {testigo.consultas()} "
        f"consultas. Si el motor dice 0, contamos algo que no llega; si dice "
        f"mas, sale mas de lo que creemos."
    )


def test_c_el_driver_añade_BEGIN_y_COMMIT_y_conviene_saberlo(testigo):
    """Lo que el motor recibe de VERDAD en una consulta ejecutada: tres.

    Nuestro contador marca 1 porque cuenta lo que envia la aplicacion. El
    driver abre y cierra la transaccion por su cuenta, y esas dos sentencias
    no pasan por el envoltorio del cursor.

    Esta prueba existe para que ese numero este ESCRITO y medido en vez de
    descubrirse el dia que alguien mire el registro del motor y crea que la
    pantalla miente. Y para que si el driver cambia de comportamiento —o si
    alguien mete un `SET` por conexion— aqui se vea.
    """
    r = ejecutar(veredicto("SELECT estado FROM cuotas LIMIT 5", CATALOGO))

    assert r.sentencias_enviadas == 1
    assert testigo.consultas() == 1
    assert testigo.todo() == 3, (
        f"El motor recibio {testigo.todo()} sentencias en total, no 3. Lo "
        f"esperado es BEGIN + la consulta + COMMIT. Si son mas, algo esta "
        f"enviando sentencias que nadie contabiliza."
    )


@pytest.mark.parametrize(
    "caso,sql",
    [
        ("M-01", "DELETE FROM pagos WHERE fecha_pago > '2026-01-01'"),
        ("M-09", "WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x"),
        ("fuera-de-alcance", "SELECT * FROM cartera.propietarios"),
    ],
)
def test_c_el_motor_confirma_CERO_sentencias_en_un_rechazo(caso, sql, testigo):
    """La afirmacion de la pantalla, comprobada desde el otro lado.

    Esta es la unica prueba del repositorio en la que el «0» no lo dice el
    codigo que lo muestra. Lo dice PostgreSQL, que anota todo lo que ese rol le
    manda y no puede ser silenciado por el.
    """
    v = veredicto(sql, CATALOGO)
    assert not v.permitido

    r = ejecutar(v)
    assert r.sentencias_enviadas == 0
    assert testigo.todo() == 0, (
        f"{caso}: nuestro contador dice 0 pero el motor anoto "
        f"{testigo.todo()} sentencias de la aplicacion. Aqui se cuenta TODO, "
        f"`BEGIN` incluido: un BEGIN suelto ya seria una conexion abierta que "
        f"la pantalla niega. La pantalla estaria afirmando un hecho falso."
    )


def test_c_el_testigo_sabe_contar_o_no_valdria_como_testigo(testigo):
    """Un testigo que siempre dijera 0 confirmaria cualquier cosa.

    Es el mismo argumento que obliga al caso positivo de la parte (a),
    aplicado al instrumento externo.
    """
    for _ in range(3):
        ejecutar(veredicto("SELECT 1 AS x FROM cuotas LIMIT 1", CATALOGO))

    assert testigo.consultas() == 3, (
        "El testigo no acumula. Si no sabe subir, su 0 no significa nada."
    )


def test_c_el_rol_de_la_aplicacion_no_puede_silenciar_al_testigo(conexion_ro):
    """Sin esta propiedad, el testigo seria decorativo: bastaria con que una
    consulta lograra apagar el registro para que dejara de constar nada."""
    import psycopg

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conexion_ro.execute("SET log_statement = 'none'")


# ---------------------------------------------------------------------------
# (d) RUIDO ACOTADO
# ---------------------------------------------------------------------------


def test_d_sin_pool_cada_consulta_abre_su_conexion(testigo):
    """Con pool, «no se abrio ninguna conexion» seria trivialmente cierto
    tambien en un resultado, y la pantalla afirmaria algo verdadero y vacio.

    Sin pool, dos consultas dan dos conexiones y dos sentencias, y el motor lo
    confirma. Es lo que hace que la frase de la pantalla signifique lo que un
    lector entiende.
    """
    r1 = ejecutar(veredicto("SELECT 1 AS a FROM cuotas LIMIT 1", CATALOGO))
    r2 = ejecutar(veredicto("SELECT 2 AS b FROM cuotas LIMIT 1", CATALOGO))

    assert r1.sentencias_enviadas == 1 and r2.sentencias_enviadas == 1, (
        "Los contadores no son independientes entre consultas."
    )
    assert testigo.consultas() == 2
    # Dos transacciones completas y separadas: 2 x (BEGIN + consulta + COMMIT).
    # Con pool serian menos, y "no se abrio ninguna conexion" cambiaria de
    # significado sin avisar.
    assert testigo.todo() == 6


def test_d_un_rechazo_entre_dos_consultas_no_deja_rastro_en_el_motor(testigo):
    """El caso realista: alguien prueba, le rechazan, y vuelve a probar.

    Las dos legitimas suman 2 en el motor. El rechazo del medio no suma nada.
    Si el ejecutor reutilizara una conexion o reintentara, aqui saldrian 3.
    """
    ejecutar(veredicto("SELECT 1 AS a FROM cuotas LIMIT 1", CATALOGO))
    ejecutar(veredicto("DROP TABLE cuotas", CATALOGO))
    ejecutar(veredicto("SELECT 2 AS b FROM cuotas LIMIT 1", CATALOGO))

    assert testigo.consultas() == 2, (
        "El rechazo del medio dejo rastro en el motor, o hubo reconexion."
    )
