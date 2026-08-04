"""
La pantalla. Una sola, sin estilo, y sin una linea de JavaScript.

POR QUE LA BIBLIOTECA ESTANDAR Y NO UN FRAMEWORK
-------------------------------------------------
El camino critico del diseño ya era "envios de formulario, cada respuesta una
pagina nueva". Con eso, un framework no aporta nada que aqui haga falta y si
añade una dependencia. Decision provisional de I-4: el guardian y el ejecutor
no dependen de esta eleccion, asi que cambiarla despues no toca nada de lo
medido.

EL ESCAPADO ES MECANISMO, NO INTENCION
---------------------------------------
Todo lo que viene del usuario o del motor pasa por `html.escape`. No hay ni una
ruta que construya marcado con texto sin escapar. El eco de la consulta
detenida es texto arbitrario controlado por quien ataca —hasta 4000
caracteres— y se renderiza: es la superficie que la politica de seguridad de
contenido cubre por debajo.

CSP SIN `unsafe-inline`
------------------------
Ni estilos ni comportamiento en linea. El CSS va en un fichero aparte. Es la
segunda capa sobre el escapado: si un escapado fallara, el navegador sigue sin
ejecutar nada.
"""

from __future__ import annotations

import html
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guardian.catalogo import Catalogo  # noqa: E402
from guardian.contrato import LIMITE_FILAS  # noqa: E402
from app import bitacora  # noqa: E402
from app.ejecutor import ejecutar  # noqa: E402
from guardian.nucleo import veredicto  # noqa: E402
from ia import contexto as ctx  # noqa: E402
from ia.orquestador import responder  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env() -> None:
    """Lee `.env` sin dependencias. Solo rellena lo que NO esté ya definido:
    una variable del entorno real siempre gana al fichero."""
    fichero = RAIZ / ".env"
    if not fichero.exists():
        return
    for linea in fichero.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env()

# El catalogo se le PASA al guardian ya cargado: leer ficheros no es trabajo de
# una funcion que debe ser pura. Quien decide de donde viene es esta capa.
import yaml  # noqa: E402

CATALOGO = Catalogo.desde_dict(
    yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))
)

TOPE_SQL = 4000
TOPE_PREGUNTA = 500

# El contexto se construye UNA vez: es determinista, y ademas asi el prefijo
# que se manda al proveedor es identico entre consultas y aplica la tarifa
# cacheada. Medido: 9216 de 9494 tokens cacheados en cuatro preguntas.
CONTEXTO = ctx.construir(
    yaml.safe_load((RAIZ / "catalogo.yaml").read_text(encoding="utf-8"))
)


def _adaptador():
    """El proveedor, o `None` si no hay clave.

    Sin clave la pantalla sigue sirviendo la via SQL entera. No es un apaño:
    es la propiedad de que la demostracion de contencion NO dependa de un
    tercero. Con el proveedor caido se siguen pudiendo enseñar el rechazo, el
    contador y la bitacora.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    from ia.adaptador import OpenAI

    return OpenAI(tope_usd=float(os.environ.get("TOPE_USD", "0.10")))


ADAPTADOR = _adaptador()

# Los ejemplos llevan su desenlace en la etiqueta A PROPOSITO: asi los tres
# comportamientos diferenciadores quedan LEIDOS sin pulsar nada, que es como un
# revisor consume una pagina. Cada etiqueta es ademas una afirmacion falsable a
# la vista: si pulsas y no ocurre lo que dice, el proyecto queda retratado.
EJEMPLOS = [
    ("SELECT unidad_codigo, saldo FROM cuotas WHERE estado = 'vencida' ORDER BY saldo DESC",
     "consulta normal → la ejecuta"),
    ("DELETE FROM pagos WHERE fecha_pago > '2026-01-01'",
     "borrar datos → lo rechaza"),
    ("WITH x AS (DELETE FROM pagos RETURNING *) SELECT * FROM x",
     "borrado escondido dentro de una consulta → también lo rechaza"),
    ("SELECT * FROM pagos WHERE valor > (SELECT MAX(salario) FROM nomina_empleados)",
     "tabla fuera de alcance, anidada → lo rechaza"),
    ("SELECT 'cartera.propietarios'::regclass",
     "preguntar si una tabla existe → lo rechaza"),
    ("SELECT * FROM cuotas WHERE fecha_vencimiento < CURRENT_DATE",
     "usar la fecha de hoy → te pide otra cosa"),
]

ALCANCE_SI = ["unidades", "propietarios", "cuotas", "pagos"]
ALCANCE_NO = [
    "nombres, documentos, correos y teléfonos de los propietarios",
    "reservas de zonas comunes",
    "intereses de mora (este conjunto no los modela)",
    "cualquier tabla que no sea una de las cuatro de la izquierda",
    "la fecha de hoy del servidor: el conjunto tiene fecha de corte fija",
]


def e(t) -> str:
    """Escapado. UNICA via por la que el texto llega al marcado."""
    return html.escape("" if t is None else str(t), quote=True)


def pagina(cuerpo: str) -> bytes:
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consultas sobre cartera con contención verificable</title>
<link rel="stylesheet" href="/estilo.css"></head>
<body><main>{cuerpo}</main></body></html>""".encode()


def formulario_pregunta() -> str:
    """El campo en español. Si no hay proveedor, se dice — no se esconde.

    Esconder el campo dejaria la pantalla coherente y la promesa del titulo
    sin cumplir en silencio. Decirlo cuesta una linea y es exacto.
    """
    if ADAPTADOR is None:
        return """<section class="cd"><h2>Preguntar en español está apagado</h2>
<p>No hay clave del proveedor configurada, así que la traducción de pregunta a
SQL no está disponible. <strong>Todo lo demás sigue funcionando</strong>: la
comprobación previa, el rechazo con su regla, el contador y el registro. Que la
demostración de contención no dependa de un tercero es una propiedad del
diseño, no una casualidad.</p></section>"""
    return f"""
<form method="get" action="/">
<label for="pregunta">Pregunta en español (máximo {TOPE_PREGUNTA} caracteres)</label>
<textarea id="pregunta" name="pregunta" rows="2"
 placeholder="¿cuánto se debe en total?"></textarea>
<p class="aviso">Un modelo escribe el SQL. <strong>Lo que escriba pasa por la
misma comprobación</strong> que si lo escribieras tú.</p>
<button type="submit">Preguntar</button>
</form>"""


def cabecera() -> str:
    filas = "".join(
        f'<li><a href="/?sql={e(sql)}"><code>{e(sql[:70])}{"…" if len(sql) > 70 else ""}'
        f"</code><span>{e(etiqueta)}</span></a></li>"
        for sql, etiqueta in EJEMPLOS
    )
    si = "".join(f"<li><code>{e(x)}</code></li>" for x in ALCANCE_SI)
    no = "".join(f"<li>{e(x)}</li>" for x in ALCANCE_NO)
    formulario = formulario_pregunta()
    return f"""
<h1>Consultas sobre datos de cartera, con contención verificable</h1>
<p class="sub">Un modelo de lenguaje escribe consultas sobre una base de datos de
cobranza. Este sistema asume que el modelo <strong>se va a equivocar</strong> y que
alguien <strong>va a intentar romperlo</strong>, y está construido para eso.</p>
<ol class="dif">
<li>Se niega a modificar datos, y dice qué regla lo impidió.</li>
<li>Cuando la pregunta es ambigua, repregunta en vez de inventarse una respuesta.</li>
<li>Enseña la consulta que se ejecutó, para que puedas comprobarla.</li>
</ol>
<p class="cd">Las reglas viven en código y tienen prueba: si se desactiva una,
el build cae — y eso también se comprueba, apagando reglas a propósito en cada
cambio. Hoy: <strong>212 pruebas en verde</strong>.</p>

{formulario}

<form method="get" action="/">
<label for="sql">…o escribe el SQL directamente (máximo {TOPE_SQL} caracteres)</label>
<textarea id="sql" name="sql" rows="4"></textarea>
<p class="aviso">Datos sintéticos, inventados para este proyecto.
No escribas datos personales reales.</p>
<button type="submit">Consultar</button>
</form>

<section class="romper"><h2>Intenta romperlo</h2>
<ul class="ejemplos">{filas}</ul></section>

<section class="alcance"><div><h3>Lo que puedes consultar</h3><ul>{si}</ul>
<p>Del 1 de enero de 2025 al 5 de julio de 2026. Fecha de corte: 5 de julio de 2026.</p></div>
<div><h3>Lo que este conjunto no tiene</h3><ul>{no}</ul>
<p class="invita">Preguntar por algo de esta columna no da error: da
«no hay datos para eso». Pruébalo.</p></div></section>
"""


def bloque_rechazo(v, r, registrado: bool) -> str:
    """El rechazo NO es un error: es la funcionalidad estrella.

    El paso 3 muestra un NUMERO MEDIDO, no un adjetivo. La linea de apoyo se
    adelanta a la objecion que el revisor se iba a hacer en silencio: «¿y quien
    me dice que ese contador no esta siempre en cero?».

    El paso 4 dice lo que DE VERDAD paso al escribir la bitacora. Durante un
    tiempo esa linea decia «si» fijo y no habia bitacora ninguna: una
    afirmacion en pantalla que nadie media, que es justo el defecto que este
    proyecto existe para no cometer. Ahora es el booleano que devuelve
    `bitacora.registrar`, y si el disco falla la pantalla dice «no».
    """
    return f"""
<section class="rechazo">
<h2>Consulta rechazada · regla {e(v.regla)}</h2>
<p class="msg">{e(v.mensaje)}</p>
<h3>Qué pasó, en orden</h3>
<ol class="pasos">
<li>Se recibió la consulta. <b>sí</b></li>
<li>La comprobación previa la revisó y la rechazó por la regla {e(v.regla)}. <b>sí</b></li>
<li>Sentencias enviadas a la base de datos: <b class="cero">{r.sentencias_enviadas}</b></li>
<li>El intento quedó registrado. <b>{"sí" if registrado else "no"}</b></li>
</ol>
<p class="apoyo">Ese {r.sentencias_enviadas} no es una frase mía: es un contador que
envuelve la conexión y cuenta cada sentencia que sale hacia el motor. Cuando una
consulta sí se ejecuta, marca 1 — pruébalo con el primer ejemplo. Hay una prueba
para los dos casos: un contador que devolviera siempre 0 la haría fallar.</p>
<h3>Consulta detenida — no se ejecutó</h3>
<pre class="detenida">{e(v.eco)}</pre>
<p class="apoyo">Esta regla no está escrita en las instrucciones que se le dan al
modelo: está en código y tiene prueba. Si alguien la desactiva, el build falla.</p>
</section>"""


def bloque_resultado(v, r) -> str:
    if r.error:
        return f"""<section class="rechazo"><h2>No pude completar la consulta</h2>
<p class="msg">{e(r.error)}</p>
<p class="apoyo">Sentencias enviadas a la base de datos:
<b>{r.sentencias_enviadas}</b>. El mensaje del motor no se muestra tal cual: se
traduce por lista blanca, porque su texto nombra objetos y columnas.</p></section>"""

    cabeceras = "".join(f"<th>{e(c)}</th>" for c in r.columnas)
    cuerpo = "".join(
        "<tr>" + "".join(f"<td>{e(c)}</td>" for c in fila) + "</tr>" for fila in r.filas
    )
    aviso = (
        f'<p class="limite">Mostrando las primeras {LIMITE_FILAS} filas. '
        f"El límite lo pone el sistema, no la consulta.</p>"
        if r.hay_mas
        else f'<p class="limite">{len(r.filas)} filas.</p>'
    )
    return f"""
<section class="ok">
<h2>1 · Lo que se pidió</h2>
<pre>{e(v.eco)}</pre>
<p class="puente">↓ La comprobación previa la aceptó y le añadió el límite de
{LIMITE_FILAS} filas. No cambió nada más.</p>
<h2>2 · Lo que se ejecutó de verdad <small>(no editable)</small></h2>
<pre>{e(v.sql_a_ejecutar)}</pre>
<p class="apoyo">Sentencias enviadas a la base de datos:
<b>{r.sentencias_enviadas}</b> · {r.ms} ms.</p>
{aviso}
<div class="tabla"><table><thead><tr>{cabeceras}</tr></thead><tbody>{cuerpo}</tbody></table></div>
</section>"""


def bloque_coherencia(v, r) -> str:
    return f"""
<section class="coherencia">
<h2>Necesito que lo preguntes de otra forma</h2>
<p class="msg">{e(v.mensaje)}</p>
<p class="apoyo">Esto no es un rechazo de seguridad: es una regla de coherencia.
Los datos tienen fecha de corte fija, así que «hoy» se consulta con
<code>consulta.fecha_corte()</code>. Sentencias enviadas:
<b>{r.sentencias_enviadas}</b>.</p>
<pre class="detenida">{e(v.eco)}</pre></section>"""


def bloque_demasiado_largo(sql: str) -> str:
    """Se ve DISTINTO de los cuatro estados del sistema, a proposito.

    Confundirlo con un rechazo del guardian devaluaria el rechazo del guardian.
    Y no se recorta: recortar en silencio produce una respuesta que parece
    correcta.
    """
    return f"""
<section class="largo">
<h2>No envié tu consulta: es demasiado larga</h2>
<p>Tu texto tiene {len(sql)} caracteres y el máximo es {TOPE_SQL}.</p>
<p class="apoyo">No la recorté. Una consulta cortada por la mitad puede seguir
siendo válida y devolver otra cosa —quitar la condición del final deja una
sentencia que corre y trae el conjunto entero—. Quita lo que no haga falta y
vuelve a enviarla.</p></section>"""


def bloque_ambigua(d) -> str:
    """La repregunta. Cada opción es un enlace a la vía SQL de siempre.

    ESO ES LO IMPORTANTE, Y NO SE VE: la opción elegida vuelve por `/?sql=` y
    **pasa el guardián otra vez**. La elección del usuario es entrada no
    confiable como cualquier otra — que el SQL lo escribiera el modelo hace un
    momento y ya pasara una validación no le da salvoconducto.

    Y no se ejecutó nada para llegar aquí. No hay «calculo la lectura más
    probable y aviso»: el error es asimétrico, porque una repregunta molesta
    es recuperable y un número con aire de certeza es invisible.
    """
    opciones = "".join(
        f'<li><a href="/?sql={e(v.sql_a_ejecutar)}"><code>{e(o.texto)}</code>'
        f"<span>{e(o.sql[:110])}{'…' if len(o.sql) > 110 else ''}</span></a></li>"
        for o, v in d.opciones
    )
    descartadas = (
        f'<p class="apoyo">El modelo ofreció {d.descartadas} opción'
        f'{"es" if d.descartadas > 1 else ""} más que la comprobación previa '
        f"descartó: no llegaron a enseñarse.</p>"
        if d.descartadas
        else ""
    )
    return f"""
<section class="coherencia">
<h2>Tu pregunta admite más de una respuesta</h2>
<p class="msg">{e(d.pregunta)}</p>
<ul class="ejemplos">{opciones}</ul>
{descartadas}
<p class="apoyo">Ninguna se ejecutó. <b>Sentencias enviadas: 0.</b> Cada opción
trae su consulta ya escrita y <b>ya validada</b>; al elegir una, vuelve a pasar
la misma comprobación. Preguntar es preferible a acertar por probabilidad: una
repregunta molesta se corrige, un número equivocado con aire de certeza no.</p>
</section>"""


def bloque_sin_datos(d) -> str:
    """«No hay datos para eso». El comportamiento que depende del modelo.

    Y se dice en pantalla, porque es la distinción que separa este bloque del
    rechazo: el rechazo lo garantiza el código; esto lo decide el modelo.
    """
    disponibles = "".join(f"<li><code>{e(x)}</code></li>" for x in d.disponibles)
    return f"""
<section class="coherencia">
<h2>No hay datos para eso</h2>
<p class="msg">Este conjunto no tiene {e(d.falta)}.</p>
<p class="apoyo">No te devuelvo una tabla que responda otra cosa parecida, que
es lo que haría un sistema servicial. <b>Sentencias enviadas: 0.</b></p>
<h3>Lo que sí hay</h3><ul>{disponibles}</ul>
<p class="apoyo"><b>Esto depende del modelo, y conviene decirlo.</b> El rechazo
de lo destructivo lo garantiza el código y está medido; reconocer una pregunta
sin respuesta, no. Si el modelo fallara aquí, lo peor que puede pasar es que
escriba una consulta que la comprobación previa rechace — nunca una tabla
inventada.</p></section>"""


def bloque_error_ia(d) -> str:
    return f"""<section class="rechazo"><h2>No pude responder</h2>
<p class="msg">{e(d.mensaje)}</p>
<p class="apoyo">Sentencias enviadas a la base de datos: <b>0</b>. Puedes
escribir el SQL directamente: esa vía no depende del proveedor del modelo.</p>
</section>"""


def bloque_pregunta_traducida(d, r) -> str:
    """La consulta que salió de una pregunta. Enseña la interpretación.

    Es RF-14: el resultado declara qué entendió el sistema. Sin eso, quien
    mira no puede saber si el número responde a su pregunta o a otra parecida.
    """
    return f"""
<section class="ok">
<h2>Lo que entendí</h2>
<p class="msg">{e(d.interpretacion)}</p>
<p class="apoyo">Si no es lo que preguntabas, la consulta de abajo te dice
exactamente por qué: es la que se ejecutó, sin retoques.</p>
</section>"""


class Manejador(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        ruta = urlparse(self.path)

        if ruta.path == "/estilo.css":
            return self._envia(
                (Path(__file__).parent / "estilo.css").read_bytes(), "text/css"
            )
        if ruta.path != "/":
            return self._envia(pagina("<h1>No existe.</h1>"), "text/html", 404)

        parametros = parse_qs(ruta.query)
        pregunta = (parametros.get("pregunta") or [""])[0]
        if pregunta.strip():
            return self._responde_pregunta(pregunta)

        sql = (parametros.get("sql") or [""])[0]
        if not sql.strip():
            return self._envia(pagina(cabecera()), "text/html")

        if len(sql) > TOPE_SQL:
            return self._envia(
                pagina(bloque_demasiado_largo(sql) + cabecera()), "text/html", 422
            )

        v = veredicto(sql, CATALOGO)
        r = ejecutar(v)
        # Se registra SIEMPRE, no solo los rechazos. RF-11 solo exige el
        # intento rechazado, pero una bitacora que solo tiene rechazos no deja
        # calcular la proporcion, que es lo que convierte el registro en un
        # dato y no en una anecdota.
        registrado = bitacora.registrar(v, r)
        if v.permitido:
            cuerpo = bloque_resultado(v, r)
        elif v.admite_reintento:
            cuerpo = bloque_coherencia(v, r)
        else:
            cuerpo = bloque_rechazo(v, r, registrado)
        return self._envia(pagina(cuerpo + cabecera()), "text/html")

    def _responde_pregunta(self, pregunta: str):
        """La vía en lenguaje natural. Termina SIEMPRE en uno de cinco sitios."""
        if ADAPTADOR is None:
            return self._envia(pagina(cabecera()), "text/html")

        d = responder(pregunta, CONTEXTO, CATALOGO, ADAPTADOR)

        if d.clase == "consulta":
            r = ejecutar(d.veredicto)
            bitacora.registrar(d.veredicto, r, via="pn")
            cuerpo = bloque_pregunta_traducida(d, r) + bloque_resultado(d.veredicto, r)
        elif d.clase == "rechazo":
            r = ejecutar(d.veredicto)
            registrado = bitacora.registrar(d.veredicto, r, via="pn")
            cuerpo = bloque_rechazo(d.veredicto, r, registrado)
        elif d.clase == "ambigua":
            cuerpo = bloque_ambigua(d)
        elif d.clase == "sin_datos":
            cuerpo = bloque_sin_datos(d)
        else:
            cuerpo = bloque_error_ia(d)

        return self._envia(pagina(cuerpo + cabecera()), "text/html")

    def _envia(self, datos: bytes, tipo: str, codigo: int = 200):
        self.send_response(codigo)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        # Segunda capa sobre el escapado. Sin `unsafe-inline`: aunque alguien
        # colara marcado, el navegador no ejecutaria nada.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, formato, *args):
        pass  # el registro de consultas es de la bitacora, no del servidor HTTP


if __name__ == "__main__":
    puerto = int(os.environ.get("PUERTO_APP", "8000"))
    print(f"  Abre  http://localhost:{puerto}")
    print("  Ctrl+C para parar\n")
    HTTPServer(("127.0.0.1", puerto), Manejador).serve_forever()
