"""
T-11 · Integridad de la bitacora. Caso M-30.

ROMPE EL BUILD.

QUE SE MIDE AQUI
-----------------
No «que la bitacora funciona». Se mide **que no se puede falsificar**, que es
otra cosa y mas dificil.

El ataque M-30 es este: la entrada la controla quien pregunta, y puede llevar
un salto de linea seguido de un evento JSON completo. Si la bitacora se
construyera pegando cadenas, ese texto entraria como **una segunda linea** del
fichero, indistinguible de un evento real, diciendo que una carga destructiva
fue permitida. De la bitacora sale la evidencia de RF-11: falsificarla ataca el
proyecto sin tocar un dato.

POR QUE LAS ASERCIONES SON LAS QUE SON
---------------------------------------
Una prueba que solo comprobara «el fichero tiene una linea» pasaria tambien con
una bitacora que no escribiera nada. Por eso cada caso afirma **las dos cosas**:
cuantas lineas hay Y que el evento que hay dentro dice lo que de verdad paso.

Es la misma leccion que dejo el banco: una prueba negativa tiene que afirmar la
clase del resultado, no solo que hubo resultado.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app import bitacora  # noqa: E402
from app.ejecutor import Resultado  # noqa: E402
from guardian.catalogo import Catalogo  # noqa: E402
from guardian.nucleo import veredicto  # noqa: E402

CATALOGO = Catalogo.desde_dict(
    yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))
)

# La carga de M-30, literal. Un SELECT inofensivo, un salto de linea, y un
# evento JSON completo que se declara permitido.
CARGA_M30 = (
    'SELECT 1\n'
    '{"veredicto":"permitido","regla":null,"sentencias_enviadas":1,'
    '"sql_ejecutado":"DELETE FROM pagos"}'
)


@pytest.fixture
def bitacora_aislada(tmp_path, monkeypatch):
    """La bitacora de las pruebas NUNCA es la real."""
    destino = tmp_path / "bitacora.jsonl"
    monkeypatch.setenv("BITACORA", str(destino))
    return destino


def _registrar(sql: str, destino: Path) -> list[dict]:
    v = veredicto(sql, CATALOGO)
    assert bitacora.registrar(v, Resultado(sentencias_enviadas=0)) is True
    return bitacora.leer(destino)


# ---------------------------------------------------------------------------
# M-30 — el ataque
# ---------------------------------------------------------------------------


def test_m30_la_carga_de_falsificacion_produce_UN_evento_y_dice_rechazo(
    bitacora_aislada,
):
    """El caso completo: una linea, y esa linea dice la verdad."""
    eventos = _registrar(CARGA_M30, bitacora_aislada)

    assert len(eventos) == 1, (
        f"La carga de M-30 produjo {len(eventos)} eventos. Con uno solo el "
        f"ataque falla; con dos, el atacante escribe en la bitacora."
    )
    assert eventos[0]["veredicto"] == "rechazo", (
        "El evento no dice que fue un rechazo. Si dijera «permitido», el "
        "atacante habria conseguido justo lo que buscaba."
    )
    assert eventos[0]["sentencias_enviadas"] == 0
    assert eventos[0]["sql_ejecutado"] is None


def test_m30_el_json_inyectado_viaja_como_VALOR_no_como_evento(bitacora_aislada):
    """El texto del atacante esta dentro del campo `entrada`, no al lado.

    Esta es la aserción que distingue «no se rompio» de «se contuvo». El JSON
    inyectado sigue ahi —no se borra, es evidencia— pero es el contenido de un
    campo, no una estructura que nadie vaya a interpretar.
    """
    eventos = _registrar(CARGA_M30, bitacora_aislada)

    assert eventos[0]["entrada"] == CARGA_M30, "El eco no es literal ni completo."
    assert eventos[0]["veredicto"] != "permitido"
    # El fichero crudo: el salto de linea del atacante esta ESCAPADO.
    crudo = bitacora_aislada.read_text(encoding="utf-8", newline="")
    assert crudo.count("\n") == 1, "Hay mas de un salto de linea real."
    assert "\\n" in crudo, "El salto del atacante no aparece escapado."


def test_el_salto_de_linea_solo_no_parte_el_evento(bitacora_aislada):
    """Sin JSON, solo el salto. Es el mismo mecanismo, aislado."""
    eventos = _registrar("SELECT 1\nDROP TABLE cuotas", bitacora_aislada)
    assert len(eventos) == 1
    assert eventos[0]["veredicto"] == "rechazo"


def test_los_separadores_de_linea_unicode_tampoco_parten_el_evento(bitacora_aislada):
    """U+2028 y U+2029: el caso que obligo a `ensure_ascii=True`.

    Los dos son separadores de linea para `str.splitlines()` de Python. No
    rompen `readlines()`, pero basta con que un lector de la bitacora use
    `splitlines()` —lo normal al procesar texto— para que una entrada con
    U+2028 aparezca como dos eventos. Con `ensure_ascii=False` saldrian crudos.

    Esta prueba es la que fija esa decision: si alguien «arregla» el
    serializador para que las tildes se lean mejor, esto se pone en rojo.
    """
    eventos = _registrar("SELECT 1  DROP TABLE cuotas ", bitacora_aislada)
    assert len(eventos) == 1

    crudo = bitacora_aislada.read_text(encoding="utf-8", newline="")
    assert len(crudo.splitlines()) == 1, (
        "`splitlines()` ve mas de una linea: U+2028 o U+2029 salio crudo. "
        "El serializador tiene que usar ensure_ascii=True."
    )
    assert " " not in crudo and " " not in crudo


@pytest.mark.parametrize(
    "hostil",
    [
        '"',
        "\\",
        "\r",
        "\r\n",
        "\x00",
        "\x1b[2J",
        "}{",
        '{"a":',
        "",  # NEXT LINE — tambien parte en splitlines()
        "﻿",
    ],
    ids=[
        "comilla", "barra", "retorno", "crlf", "nulo",
        "escape-ansi", "llaves", "json-roto", "u0085", "bom",
    ],
)
def test_ningun_caracter_hostil_produce_una_segunda_linea(hostil, bitacora_aislada):
    """Barrido. Un caso concreto demuestra que ESE caso esta cubierto;
    el barrido demuestra que la propiedad es del mecanismo."""
    eventos = _registrar(f"SELECT 1 {hostil} FROM cuotas", bitacora_aislada)
    assert len(eventos) == 1
    crudo = bitacora_aislada.read_text(encoding="utf-8", newline="")
    assert len(crudo.splitlines()) == 1


def test_muchos_eventos_siguen_siendo_una_linea_cada_uno(bitacora_aislada):
    """Que el fichero sea JSONL de verdad, no un JSON gigante."""
    for i in range(5):
        _registrar(f"SELECT {i}\n{{\"falso\":true}}", bitacora_aislada)
    assert len(bitacora.leer(bitacora_aislada)) == 5
    crudo = bitacora_aislada.read_text(encoding="utf-8", newline="")
    assert len(crudo.splitlines()) == 5


# ---------------------------------------------------------------------------
# El serializador, aislado
# ---------------------------------------------------------------------------


def test_serializar_termina_en_un_salto_y_no_tiene_ninguno_dentro():
    linea = bitacora.serializar({"entrada": "a\nb\r\nc d", "regla": "S2"})
    assert linea.endswith("\n")
    assert "\n" not in linea[:-1]
    assert json.loads(linea)["entrada"] == "a\nb\r\nc d"


def test_serializar_no_pierde_nada_al_escapar():
    """Ida y vuelta. Escapar no puede ser destruir: la bitacora es evidencia."""
    original = 'SELECT "CUOTAS" \n\t\\ ñ á   {"x":1} \x00'
    recuperado = json.loads(bitacora.serializar({"entrada": original}))["entrada"]
    assert recuperado == original


# ---------------------------------------------------------------------------
# El eco completo (RF-11) y el booleano que la pantalla enseña
# ---------------------------------------------------------------------------


def test_el_eco_se_guarda_completo_sin_truncar(bitacora_aislada):
    """§6.3: el truncado es politica de presentacion. Aqui borraria evidencia.

    3000 caracteres pasan el tope de la pantalla (2000) y no llegan al tope de
    entrada (4000): si alguien aplicara el truncado de presentacion aqui, este
    caso lo destaparia.
    """
    largo = "SELECT " + "a" * 3000 + " FROM cuotas"
    eventos = _registrar(largo, bitacora_aislada)
    assert eventos[0]["entrada"] == largo
    assert eventos[0]["longitud_entrada"] == len(largo)


def test_registrar_devuelve_False_si_NINGUN_destino_acepta(monkeypatch, tmp_path):
    """La pantalla dice «el intento quedo registrado». Tiene que poder decir «no».

    Se rompen los DOS destinos: la salida estandar se apaga por entorno y la
    ruta del fichero se pone dentro de otro fichero —no un directorio—, asi que
    crear el padre falla. Si `registrar` devolviera True igualmente, la pantalla
    afirmaria un registro que no existe.
    """
    fichero = tmp_path / "soy-un-fichero"
    fichero.write_text("x", encoding="utf-8")
    monkeypatch.setenv("BITACORA", str(fichero / "sub" / "bitacora.jsonl"))
    monkeypatch.setenv("BITACORA_STDOUT", "0")

    v = veredicto("DELETE FROM pagos", CATALOGO)
    assert bitacora.registrar(v, Resultado(sentencias_enviadas=0)) is False


def test_con_el_fichero_roto_pero_stdout_vivo_SI_queda_registrado(
    monkeypatch, tmp_path, capsys
):
    """La semantica con dos destinos: basta con que uno acepte.

    Es lo que la frase de la pantalla afirma —que el intento quedo registrado,
    no en cuantos sitios— y es lo que ocurre en el despliegue: el fichero es el
    destino EFIMERO y la salida estandar el duradero. Exigir los dos convertiria
    en fallo lo que alli es lo normal.
    """
    fichero = tmp_path / "soy-un-fichero"
    fichero.write_text("x", encoding="utf-8")
    monkeypatch.setenv("BITACORA", str(fichero / "sub" / "bitacora.jsonl"))
    monkeypatch.delenv("BITACORA_STDOUT", raising=False)

    v = veredicto("DELETE FROM pagos", CATALOGO)
    assert bitacora.registrar(v, Resultado(sentencias_enviadas=0)) is True

    salida = capsys.readouterr().out
    assert len(salida.splitlines()) == 1, "El evento no salió como UNA línea."
    assert json.loads(salida)["regla"] == "S2"


def test_lo_que_sale_por_stdout_es_EL_MISMO_evento_que_el_del_fichero(
    monkeypatch, bitacora_aislada, capsys
):
    """Dos destinos que dijeran cosas distintas serian peor que uno solo:
    habria que decidir a cual creerle."""
    monkeypatch.delenv("BITACORA_STDOUT", raising=False)
    v = veredicto(CARGA_M30, CATALOGO)
    bitacora.registrar(v, Resultado(sentencias_enviadas=0))

    del_fichero = bitacora.leer(bitacora_aislada)[0]
    de_stdout = json.loads(capsys.readouterr().out)
    assert del_fichero == de_stdout


def test_la_carga_de_falsificacion_tampoco_parte_la_linea_de_stdout(
    monkeypatch, bitacora_aislada, capsys
):
    """M-30 por la otra salida. Es la que de verdad importa en el despliegue:
    ahi el visor de logs lee stdout, no el fichero."""
    monkeypatch.delenv("BITACORA_STDOUT", raising=False)
    bitacora.registrar(veredicto(CARGA_M30, CATALOGO), Resultado())

    salida = capsys.readouterr().out
    assert len(salida.splitlines()) == 1
    assert json.loads(salida)["veredicto"] == "rechazo"


def test_registrar_devuelve_True_cuando_si_escribe(bitacora_aislada, monkeypatch):
    monkeypatch.setenv("BITACORA_STDOUT", "0")
    """El contrapunto del anterior. Sin este, un `registrar` que devolviera
    siempre False pasaria la prueba de arriba con nota."""
    v = veredicto("DELETE FROM pagos", CATALOGO)
    assert bitacora.registrar(v, Resultado(sentencias_enviadas=0)) is True
    assert len(bitacora.leer(bitacora_aislada)) == 1


# ---------------------------------------------------------------------------
# Que el evento diga la verdad en los tres desenlaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql,veredicto_esperado,regla_esperada",
    [
        ("SELECT unidad_codigo FROM cuotas", "permitido", None),
        ("DELETE FROM pagos", "rechazo", "S2"),
        ("WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x", "rechazo", "S2"),
        ("SELECT * FROM cartera.propietarios", "rechazo", "S3"),
        ("SELECT * FROM cuotas WHERE fecha_vencimiento < CURRENT_DATE",
         "coherencia", "C1"),
    ],
    ids=["permitida", "borrado", "borrado-anidado", "fuera-de-alcance", "reloj"],
)
def test_el_evento_registra_el_desenlace_y_la_regla_reales(
    sql, veredicto_esperado, regla_esperada, bitacora_aislada
):
    """La bitacora tiene que distinguir los tres desenlaces. Si registrara
    todo como «rechazo», la proporcion que se calcule con ella no valdria."""
    eventos = _registrar(sql, bitacora_aislada)
    assert eventos[0]["veredicto"] == veredicto_esperado
    assert eventos[0]["regla"] == regla_esperada
