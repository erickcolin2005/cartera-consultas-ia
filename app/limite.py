"""
Limite de tasa por IP. Lo que se pone entre un desconocido y la factura.

POR QUE EXISTE ESTE FICHERO
----------------------------
M-27 es la unica fila del banco que la suite se salta, y su criterio dice por
que: *"Fallo si no existe NINGUN mecanismo entre el atacante y la factura salvo
D13"*. D13 es el tope duro de gasto en la consola del proveedor: la red final.
Depender solo de ella significa que la primera señal de un ataque de volumen es
que la demo deja de funcionar porque se acabo el dinero.

Esto es el mecanismo que faltaba. No sustituye a D13 —nada lo sustituye— pero
hace que haya algo antes.

VENTANA FIJA, NO CUBO DE FICHAS
--------------------------------
Se cuenta cuantas peticiones ha hecho una IP en la ventana actual y se corta al
llegar al tope. Un cubo de fichas seria mas suave con las rafagas legitimas, y
aqui la suavidad no es una virtud: quien pregunta escribe en español y tarda
segundos entre preguntas. El caso que hay que parar es "100 seguidas sin
pausa", y para eso la ventana fija es mas simple de entender y de auditar.

Coste declarado: en el peor caso se admiten casi el doble del tope entre dos
ventanas contiguas. Con 10 por minuto eso son 20 en un instante, y 20 preguntas
son unos dos centimos. Es un limite conocido, no un descuido.

LO QUE ESTO NO ES, Y HAY QUE DECIRLO
-------------------------------------
**No protege de un atacante con muchas IP.** Nada en este fichero lo hace, y
fingir lo contrario seria peor que no tenerlo.

**Vive en el proceso.** Se reinicia con el proceso, y si algun dia hay dos
instancias, cada una lleva su cuenta. Para esta demo —una sola instancia— es
exacto; para mas de una, haria falta un contador compartido.

**La IP puede no ser la del visitante.** Detras de un proxy o un balanceador,
la direccion del socket es la del proxy y TODO el trafico compartiria cubo. Por
eso se lee `X-Forwarded-For` cuando se declara explicitamente que hay un proxy
delante —y solo entonces: confiar en esa cabecera sin proxy es regalarle al
atacante la forma de saltarse el limite escribiendo una cabecera.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Preguntas al modelo por IP y minuto. Una persona escribiendo en español no
# pasa de unas pocas; 100 seguidas es el ataque que describe M-27.
TOPE_PREGUNTAS = 10
VENTANA_SEGUNDOS = 60

# La via SQL no cuesta dinero en el proveedor, pero si abre conexiones y
# consume el cupo del rol (CONNECTION LIMIT 10). Se limita mas holgada: el
# objetivo aqui es la disponibilidad, no la factura.
TOPE_SQL = 60


@dataclass
class Limite:
    """Cuenta peticiones por IP en una ventana fija.

    El reloj se inyecta para que las pruebas no dependan de dormir. Una prueba
    de limite de tasa que usa `sleep` es lenta y ademas intermitente en una
    maquina cargada, que es como acaba desactivada.
    """

    tope: int
    ventana: float = VENTANA_SEGUNDOS
    reloj: object = time.monotonic
    _cuentas: dict[str, tuple[float, int]] = field(default_factory=dict)

    def admite(self, ip: str) -> bool:
        """True si la peticion pasa. Cuenta como consumida solo si pasa.

        Que una peticion RECHAZADA no consuma cupo es deliberado: si contara,
        quien ataca extenderia su propio castigo indefinidamente y una persona
        que se pasa por poco quedaria bloqueada mientras el ataque siguiera.
        """
        ahora = self.reloj()
        inicio, usadas = self._cuentas.get(ip, (ahora, 0))

        if ahora - inicio >= self.ventana:
            inicio, usadas = ahora, 0

        if usadas >= self.tope:
            self._cuentas[ip] = (inicio, usadas)
            return False

        self._cuentas[ip] = (inicio, usadas + 1)
        return True

    def restantes(self, ip: str) -> int:
        ahora = self.reloj()
        inicio, usadas = self._cuentas.get(ip, (ahora, 0))
        if ahora - inicio >= self.ventana:
            return self.tope
        return max(0, self.tope - usadas)

    def olvidar_viejas(self) -> int:
        """Quita las IP cuya ventana ya expiro. Devuelve cuantas quito.

        Sin esto el diccionario crece con cada IP que aparece una vez, y un
        barrido de direcciones lo convierte en una fuga de memoria lenta. No es
        una optimizacion: es la diferencia entre un limite que aguanta un mes y
        uno que hay que reiniciar.
        """
        ahora = self.reloj()
        viejas = [
            ip for ip, (inicio, _) in self._cuentas.items()
            if ahora - inicio >= self.ventana
        ]
        for ip in viejas:
            del self._cuentas[ip]
        return len(viejas)


def ip_del_cliente(direccion: str, cabeceras, hay_proxy: bool) -> str:
    """La IP a la que se le cuenta la peticion.

    `X-Forwarded-For` SOLO se lee si se declara que hay un proxy delante. Sin
    esa condicion, cualquiera se saltaria el limite mandando la cabecera con un
    valor distinto en cada peticion — el limite existiria y no limitaria nada.

    Se toma la PRIMERA de la lista, que es la del cliente original; las
    siguientes las añaden los saltos intermedios.
    """
    if not hay_proxy:
        return direccion
    reenviada = cabeceras.get("X-Forwarded-For", "")
    if not reenviada:
        return direccion
    return reenviada.split(",")[0].strip() or direccion


MENSAJE = (
    "Vas muy rápido. Este sistema es una demostración con presupuesto acotado, "
    "así que limita las preguntas por minuto. Espera un momento y vuelve a "
    "intentarlo."
)
