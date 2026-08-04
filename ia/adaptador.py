"""
El adaptador de OpenAI. El UNICO modulo de `ia/` que toca la red.

POR QUE ESTA SOLO EN SU FICHERO
--------------------------------
Todo lo demas de `ia/` es puro y se mide sin gastar un centimo: el contexto, el
contrato, el orquestador. Si la llamada viviera dentro del orquestador, T-3 y
T-4 necesitarian un proveedor en pie para correr, y una prueba de contencion
que depende de un tercero es una prueba que un dia deja de correr.

SALIDA ESTRUCTURADA IMPUESTA, NO PEDIDA (E-2)
-----------------------------------------------
Se envia `response_format` con el esquema del contrato y `strict: true`. La
diferencia con pedirlo en el prompt no es de estilo: si el formato es una
sugerencia, F-1 dispara reintentos y `k` deja de ser 1 — el coste por pregunta
se dobla por una razon evitable.

EL TOPE DE GASTO, Y POR QUE ESTE NO ES EL DE VERDAD
-----------------------------------------------------
El diseño pide un tope DURO en la consola del proveedor (E-1): es la unica
defensa que sigue en pie si todo el codigo falla. Este contador **no es eso**.
Vive en el proceso, se reinicia al reiniciar, y no sabe nada del gasto hecho
por otras vias.

Es una segunda capa util —para que un bucle o una rafaga no vacien el saldo en
un minuto— y esta declarada como tal. **En OpenAI el tope duro real es el saldo
prepagado con la recarga automatica apagada**: cuando llega a cero, las
llamadas fallan. Eso si sobrevive a cualquier fallo de este fichero.

LA CLAVE NUNCA SE IMPRIME
--------------------------
Ni en un error, ni en un registro, ni en un mensaje al usuario. Los errores del
proveedor se traducen a `ProveedorCaido` con texto propio: el cuerpo de la
respuesta de un 401 puede llevar informacion de la cuenta.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from ia.contrato import ESQUEMA_SALIDA
from ia.orquestador import ProveedorCaido

URL = "https://api.openai.com/v1/chat/completions"

# Fijado a proposito. E-3 del diseño: si el modelo cambia bajo los pies, C1
# deja de ser reproducible y la tabla de resultados deja de significar nada.
MODELO = "gpt-4o-mini"

# Un SELECT no necesita miles. Fijarlo es gratis y evita una salida desbocada.
# Las repreguntas son lo que marca el suelo: llevan hasta cuatro SQL.
TOPE_TOKENS_SALIDA = 900

SEGUNDOS_DE_ESPERA = 30

# Precios por millon de tokens, en USD, POR MODELO.
#
# Estaban escritos sueltos, validos solo para gpt-4o-mini. Al probar otro
# modelo el medidor siguio calculando con los precios del primero y devolvio
# una cifra falsa sin avisar — exactamente el tipo de numero que este proyecto
# no acepta. El fallo no fue el precio: fue que una constante global se
# aplicara a un parametro variable.
#
# Cada entrada lleva la FECHA en que se verifico. Un precio sin fecha es un
# numero que envejece en silencio.
PRECIOS: dict[str, dict[str, float]] = {
    # Verificados por Erick contra la pagina de precios de OpenAI, 2026-08-03.
    "gpt-4o-mini": {
        "entrada": 0.15 / 1_000_000,
        "cacheada": 0.075 / 1_000_000,
        "salida": 0.60 / 1_000_000,
        "verificado": "2026-08-03",
    },
}


class PrecioDesconocido(ValueError):
    """No hay precio verificado para ese modelo.

    Falla CERRADO a proposito. La alternativa —estimar con el precio de otro
    modelo, o poner cero— daria un medidor que responde siempre y acierta a
    veces, y un medidor asi es peor que no tenerlo: se le cree.
    """


@dataclass
class Gasto:
    """Lo gastado por este proceso. Medido con lo que devuelve la API.

    No es una estimacion por caracteres: son los tokens que el proveedor dice
    haber cobrado. Un contador estimado seria justo el tipo de cifra que este
    proyecto no acepta.
    """

    modelo: str = MODELO
    llamadas: int = 0
    tokens_entrada: int = 0
    tokens_cacheados: int = 0
    tokens_salida: int = 0

    @property
    def usd(self) -> float:
        precios = PRECIOS.get(self.modelo)
        if precios is None:
            raise PrecioDesconocido(
                f"No hay precio verificado para `{self.modelo}`. Añádelo a "
                f"PRECIOS con la fecha en que lo comprobaste. Sin eso el "
                f"medidor daría una cifra inventada."
            )
        frescos = self.tokens_entrada - self.tokens_cacheados
        return (
            frescos * precios["entrada"]
            + self.tokens_cacheados * precios["cacheada"]
            + self.tokens_salida * precios["salida"]
        )


class PresupuestoAgotado(ProveedorCaido):
    """Se alcanzo el tope del proceso. Hereda de `ProveedorCaido` a proposito:
    el orquestador ya sabe no reintentar ante el, y el usuario recibe el mismo
    mensaje fijo. Un mensaje propio diria cuanto dinero queda, que no es asunto
    de quien pregunta."""


class OpenAI:
    """El proveedor real. Una llamada, salida tipada, sin conversacion."""

    def __init__(
        self,
        clave: str | None = None,
        *,
        modelo: str = MODELO,
        tope_usd: float = 0.10,
    ) -> None:
        self.clave = clave or os.environ.get("OPENAI_API_KEY", "")
        if not self.clave:
            raise ValueError(
                "Falta OPENAI_API_KEY. Va en el fichero .env, que está en "
                ".gitignore y no sube al repositorio."
            )
        if modelo not in PRECIOS:
            raise PrecioDesconocido(
                f"No hay precio verificado para `{modelo}`. El tope de gasto "
                f"no podría calcularse, así que no se permite usarlo."
            )
        self.modelo = modelo
        self.tope_usd = tope_usd
        self.gasto = Gasto(modelo=modelo)

    def preguntar(
        self, contexto: str, pregunta: str, pista: str | None = None
    ) -> str:
        if self.gasto.usd >= self.tope_usd:
            raise PresupuestoAgotado(
                f"tope del proceso alcanzado: {self.gasto.usd:.4f} USD"
            )

        # El contexto va en `system` y la pregunta en `user`, separados. Es lo
        # que permite que el prefijo sea IDENTICO entre consultas y que la
        # tarifa de entrada cacheada aplique — la mitad de precio. Por eso el
        # constructor de contexto es determinista y hay una prueba que lo fija.
        mensajes = [
            {"role": "system", "content": contexto},
            {"role": "user", "content": pregunta},
        ]
        if pista:
            mensajes.append({"role": "system", "content": pista})

        cuerpo = json.dumps(
            {
                "model": self.modelo,
                "messages": mensajes,
                "max_completion_tokens": TOPE_TOKENS_SALIDA,
                # Determinismo dentro de lo que el proveedor permite: la misma
                # pregunta no deberia dar SQL distinto cada vez, o C1 mediria
                # ruido.
                "temperature": 0,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "respuesta_cartera",
                        "strict": True,
                        "schema": ESQUEMA_SALIDA,
                    },
                },
            }
        ).encode("utf-8")

        peticion = urllib.request.Request(
            URL,
            data=cuerpo,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.clave}",
            },
        )

        try:
            with urllib.request.urlopen(peticion, timeout=SEGUNDOS_DE_ESPERA) as r:
                datos = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # NO se propaga el cuerpo: un 401 o un 429 pueden llevar
            # informacion de la cuenta, y de aqui sale texto que acaba cerca
            # del usuario.
            raise ProveedorCaido(f"el proveedor respondió {e.code}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise ProveedorCaido(f"no se pudo hablar con el proveedor: {type(e).__name__}") from None

        uso = datos.get("usage") or {}
        detalle = uso.get("prompt_tokens_details") or {}
        self.gasto.llamadas += 1
        self.gasto.tokens_entrada += uso.get("prompt_tokens", 0)
        self.gasto.tokens_cacheados += detalle.get("cached_tokens", 0)
        self.gasto.tokens_salida += uso.get("completion_tokens", 0)

        try:
            return datos["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            # Sin contenido no hay nada que interpretar. Se trata como fallo de
            # forma (F-1) devolviendo texto vacio: el contrato lo rechazara y
            # el orquestador reintentara una vez, que es la conducta correcta.
            return ""
