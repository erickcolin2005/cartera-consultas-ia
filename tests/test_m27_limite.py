"""
M-27 · El mecanismo entre un desconocido y la factura.

ROMPE EL BUILD. Y cierra la única fila del banco que la suite se saltaba.

QUE PEDIA M-27, LITERALMENTE
------------------------------
    receta:   una pregunta de 500 caracteres exactos, 100 veces seguidas sin
              pausa, desde la misma IP
    intenta:  consumir el presupuesto del proveedor. No busca datos: busca la
              factura
    criterio: **fallo si no existe NINGÚN mecanismo entre el atacante y la
              factura salvo D13**

D13 es el tope duro en la consola del proveedor: la red final. Depender solo de
ella significa que la primera señal de un ataque es que la demo dejó de
funcionar porque se acabó el dinero. Estas pruebas fijan que hay algo antes.

POR QUE EL RELOJ SE INYECTA
-----------------------------
Una prueba de límite de tasa que usa `sleep` es lenta y, en una máquina
cargada, intermitente. Y una prueba intermitente acaba desactivada — que es
justo lo que le pasó a M-27 durante todo el proyecto, aunque por otra razón.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.limite import Limite, ip_del_cliente  # noqa: E402


class RelojFalso:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def avanza(self, segundos: float) -> None:
        self.t += segundos


# ---------------------------------------------------------------------------
# La receta de M-27, tal cual
# ---------------------------------------------------------------------------


def test_m27_cien_peticiones_seguidas_desde_una_ip_no_pasan():
    """El caso del banco, literal. Si esto pasara, no habría nada entre el
    atacante y la factura salvo el tope de la consola."""
    reloj = RelojFalso()
    limite = Limite(tope=10, reloj=reloj)

    admitidas = sum(limite.admite("203.0.113.7") for _ in range(100))

    assert admitidas == 10, (
        f"Pasaron {admitidas} de 100. El límite no está limitando."
    )


def test_m27_lo_que_esas_cien_peticiones_habrian_costado():
    """El número que hace concreta la amenaza.

    A ~$0,0004 por pregunta, 100 seguidas son unos 4 céntimos. Parece poco, y
    ese es exactamente el punto: **repetido sin límite no lo es**. Con el
    límite, un atacante desde una IP no pasa de 10 por minuto.
    """
    reloj = RelojFalso()
    limite = Limite(tope=10, reloj=reloj)
    coste_por_pregunta = 0.0004

    sin_limite = 100 * coste_por_pregunta
    con_limite = sum(limite.admite("203.0.113.7") for _ in range(100)) * coste_por_pregunta

    assert con_limite < sin_limite / 9
    assert con_limite == pytest.approx(0.004, abs=1e-6)


def test_una_ip_bloqueada_no_bloquea_a_las_demas():
    """Si el límite fuera global, un atacante dejaría la demo inservible para
    todos con una ráfaga. El cubo es por IP a propósito."""
    reloj = RelojFalso()
    limite = Limite(tope=3, reloj=reloj)

    for _ in range(10):
        limite.admite("198.51.100.1")

    assert limite.admite("203.0.113.9") is True


def test_la_ventana_se_reabre_cuando_pasa_el_tiempo():
    reloj = RelojFalso()
    limite = Limite(tope=3, ventana=60, reloj=reloj)

    assert [limite.admite("ip") for _ in range(4)] == [True, True, True, False]
    reloj.avanza(61)
    assert limite.admite("ip") is True


def test_una_peticion_rechazada_no_consume_cupo():
    """Si contara, quien ataca extendería su propio castigo indefinidamente, y
    una persona que se pasa por poco quedaría bloqueada mientras el ataque
    siguiera. El castigo no puede depender del atacante."""
    reloj = RelojFalso()
    limite = Limite(tope=2, ventana=60, reloj=reloj)

    limite.admite("ip"); limite.admite("ip")
    for _ in range(50):
        assert limite.admite("ip") is False

    reloj.avanza(61)
    assert limite.admite("ip") is True, (
        "Tras la ventana sigue bloqueada: los rechazos consumieron cupo."
    )


def test_el_diccionario_no_crece_sin_fin():
    """Un barrido de direcciones convertiría el límite en una fuga de memoria
    lenta: aguantaría un día y habría que reiniciar."""
    reloj = RelojFalso()
    limite = Limite(tope=5, ventana=60, reloj=reloj)

    for i in range(1000):
        limite.admite(f"10.0.{i // 256}.{i % 256}")
    reloj.avanza(61)

    assert limite.olvidar_viejas() == 1000
    assert limite._cuentas == {}


# ---------------------------------------------------------------------------
# La cabecera del proxy: el fallo clásico de estos límites
# ---------------------------------------------------------------------------


def test_sin_proxy_declarado_la_cabecera_se_IGNORA():
    """El fallo que hace inútil a la mayoría de estos límites.

    Si se leyera `X-Forwarded-For` siempre, cualquiera se saltaría el límite
    mandando un valor distinto en cada petición: el límite existiría y no
    limitaría nada. Se lee solo cuando se declara que hay un proxy delante.
    """
    cabeceras = {"X-Forwarded-For": "1.2.3.4"}
    assert ip_del_cliente("198.51.100.1", cabeceras, hay_proxy=False) == "198.51.100.1"


def test_con_proxy_declarado_se_toma_la_primera_de_la_cadena():
    """La primera es la del cliente original; las siguientes las añaden los
    saltos intermedios."""
    cabeceras = {"X-Forwarded-For": "203.0.113.5, 70.41.3.18, 150.172.238.178"}
    assert ip_del_cliente("10.0.0.1", cabeceras, hay_proxy=True) == "203.0.113.5"


def test_con_proxy_pero_sin_cabecera_se_usa_la_direccion_del_socket():
    assert ip_del_cliente("10.0.0.1", {}, hay_proxy=True) == "10.0.0.1"


def test_un_ataque_con_cabecera_falsificada_no_multiplica_el_cupo():
    """La prueba que junta las dos piezas: sin proxy, cambiar la cabecera en
    cada petición no da un cubo nuevo cada vez."""
    reloj = RelojFalso()
    limite = Limite(tope=5, reloj=reloj)

    admitidas = 0
    for i in range(50):
        ip = ip_del_cliente("198.51.100.1", {"X-Forwarded-For": f"9.9.9.{i}"}, False)
        admitidas += limite.admite(ip)

    assert admitidas == 5
