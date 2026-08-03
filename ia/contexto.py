"""
El contexto que se le envia al modelo. Ocho bloques, todos desde el catalogo.

QUE ES ESTE MODULO, EN UNA FRASE
---------------------------------
Convierte `catalogo.yaml` en el texto que acompaña a la pregunta. Nada mas.
Es una funcion pura: mismo catalogo, mismo texto. Sin red, sin reloj, sin
base de datos.

CD1 — LA CONTENCION NO PUEDE VIVIR AQUI
----------------------------------------
Este fichero es el sitio mas tentador del proyecto para escribir «y no borres
nada». Esa frase seria inutil y peor que inutil: da la sensacion de proteger.
**Ninguna regla de contencion depende de este texto.** El bloque 1 dice «SQL de
solo lectura», que orienta al modelo, pero T-4 borra el bloque entero y el
guardian rechaza exactamente lo mismo. CD1 prohibe que la contencion DEPENDA
del prompt, no que el prompt oriente.

Hay una linea del catalogo que roza el limite y esta anotada alli: «contacto de
los propietarios: telefono, correo o documento» dentro de las ausencias. Es una
regla de ocultacion que vive en el texto. No viola CD1 —la vista no publica esas
columnas y el motor las rechaza— pero es exactamente la que un cambio futuro
puede convertir en la unica defensa sin que nadie lo note (R-20).

D6 — QUE SALE Y QUE NO, DICHO CON PRECISION
--------------------------------------------
De las tablas no sale nada: ni una fila, ni una muestra, ni un agregado. Este
modulo **no importa nada que pueda leer datos** y T-5 lo comprueba leyendo el
codigo fuente, no confiando en que se cumpla.

Pero la frase corta —«al modelo solo le llega el esquema»— es falsa, y conviene
decirlo aqui donde se construye el texto: **sale la pregunta tal como la
escribio el usuario**. Los datos de cartera son sinteticos y no tienen titular;
el texto del visitante si puede tenerlo. Es la unica pieza del sistema que
puede mandar un dato personal real fuera del pais.

POR QUE EL ORDEN DE LOS BLOQUES ES EL QUE ES
----------------------------------------------
Los bloques 5, 6 y 7 son los que un tutorial no tiene, y cada uno produce un
comportamiento concreto:

  5 · reglas de negocio  -> el modelo sabe que es «mora» sin adivinarlo
  6 · rangos de fechas   -> «cuanto se recaudo en 2023» no devuelve una tabla
                            vacia que el usuario lea como un cero
  7 · ausencias          -> hace posible D-D. Sin una lista explicita de lo que
                            no existe, un modelo servicial busca el concepto
                            mas parecido y responde otra cosa

La pregunta va la ULTIMA, despues de todo el material. Es tambien lo que
permite que el prefijo sea identico entre consultas.
"""

from __future__ import annotations

from typing import Any

# El unico sitio donde se escribe texto a mano. Todo lo demas sale del
# catalogo. Si esto creciera, seria señal de que una regla de negocio se esta
# escribiendo aqui en vez de en el catalogo, que es donde se revisa.
_PAPEL = """\
Traduces preguntas sobre cartera y cobranza de una copropiedad a SQL de \
PostgreSQL de solo lectura.

Respondes SIEMPRE con un unico objeto JSON, sin texto alrededor, de uno de \
estos tres tipos:

{"tipo": "consulta",
 "sql": "SELECT ...",
 "interpretacion": "que entendiste, en una linea y en español"}

{"tipo": "ambigua",
 "pregunta": "la pregunta admite mas de una respuesta correcta. ¿Cual quieres?",
 "opciones": [{"id": "a", "texto": "...", "sql": "SELECT ..."},
              {"id": "b", "texto": "...", "sql": "SELECT ..."}]}

{"tipo": "sin_datos",
 "falta": "lo que la pregunta pide y este conjunto no tiene",
 "disponibles": ["unidades", "propietarios", "cuotas", "pagos"]}

Como elegir el tipo:

- Usa "ambigua" cuando la pregunta admita varias lecturas razonables que dan \
numeros distintos. Da entre 2 y 4 opciones, CADA UNA con su SQL ya escrito. \
No ejecutes una lectura y avises: pregunta.
- Usa "sin_datos" cuando la pregunta pida algo que este conjunto no contiene. \
Si una parte es respondible y otra no, usa "sin_datos" igualmente y di que \
falta: no respondas la mitad sin advertirlo, porque quien pregunta leera la \
respuesta como completa.
- Ante la duda entre "ambigua" y "sin_datos", usa "ambigua".

Reglas al escribir SQL:

- Solo SELECT. Una sola sentencia, sin punto y coma final.
- Usa solo las relaciones y columnas que aparecen abajo.
- No uses la fecha de hoy del servidor. Este conjunto tiene fecha de corte \
fija: para decir "hoy" usa consulta.fecha_corte().
- No pongas LIMIT salvo que la pregunta pida un tope ("los 10 que mas..."). \
El sistema impone el suyo.\
"""


def _bloque_esquema(catalogo: dict[str, Any]) -> str:
    lineas = ["ESQUEMA — las unicas relaciones que puedes consultar:"]
    for concepto in catalogo["conceptos"]:
        lineas.append("")
        lineas.append(f"{concepto['relacion']}")
        lineas.append(f"  {' '.join(concepto['negocio'].split())}")
        for col in concepto["columnas"]:
            lineas.append(f"    {col['n']:<20} {col['tipo']:<8} {col['negocio']}")
    return "\n".join(lineas)


def _bloque_reglas(catalogo: dict[str, Any]) -> str:
    reglas = "\n".join(f"  - {' '.join(r.split())}" for r in catalogo["reglas_de_negocio"])
    return f"REGLAS DE NEGOCIO — como se calculan las cosas aqui:\n{reglas}"


def _bloque_valores(catalogo: dict[str, Any]) -> str:
    lineas = ["VALORES POSIBLES — estas columnas solo toman estos valores:"]
    for columna, valores in catalogo["valores_permitidos"].items():
        lineas.append(f"  {columna}: {', '.join(valores)}")
    return "\n".join(lineas)


def _bloque_rangos(catalogo: dict[str, Any]) -> str:
    """El bloque que evita el cero falso.

    Sin el, «cuanto se recaudo en 2023» produce una tabla vacia, y una tabla
    vacia se lee como «no se recaudo nada». No es un error del motor ni del
    guardian: es una respuesta correcta a una pregunta mal informada.
    """
    lineas = [
        "RANGO DE LOS DATOS — fuera de estas fechas no hay nada, y una consulta",
        "que caiga fuera devuelve una tabla vacia que se lee como un cero:",
    ]
    for columna, r in catalogo["rangos"].items():
        lineas.append(f"  {columna}: de {r['desde']} a {r['hasta']}")
    lineas.append(f"  fecha de corte: {catalogo['fecha_corte']}")
    return "\n".join(lineas)


def _bloque_ausencias(catalogo: dict[str, Any]) -> str:
    faltan = "\n".join(f"  - {a}" for a in catalogo["NO_hay_datos_de"])
    return (
        "LO QUE ESTE CONJUNTO NO TIENE — si la pregunta pide algo de esta "
        "lista,\nresponde con tipo \"sin_datos\" y no busques un sustituto "
        "parecido:\n" + faltan
    )


# Pares curados. Escritos a mano, y a proposito son POCOS y variados: cubren
# una consulta simple, una union, un agregado por mes, la fecha de corte y —la
# que mas enseña— una ambigua. No son los casos del banco: usar el banco aqui
# invalidaria la medicion de C1, porque el modelo estaria viendo el examen.
_PARES = [
    (
        "¿Cuanto se debe en total?",
        '{"tipo": "consulta", "sql": "SELECT SUM(saldo) AS cartera_total FROM '
        'consulta.cuotas WHERE saldo > 0", "interpretacion": "Suma de los saldos '
        'pendientes de todas las cuotas"}',
    ),
    (
        "¿Que unidades estan en mora?",
        '{"tipo": "consulta", "sql": "SELECT unidad_codigo, SUM(saldo) AS deuda '
        "FROM consulta.cuotas WHERE estado = 'vencida' GROUP BY unidad_codigo "
        'ORDER BY deuda DESC", "interpretacion": "Unidades con al menos una cuota '
        'vencida a la fecha de corte, y cuanto deben"}',
    ),
    (
        "¿Cuanto se recaudo cada mes?",
        '{"tipo": "consulta", "sql": "SELECT date_trunc(\'month\', fecha_pago) AS '
        "mes, SUM(valor) AS recaudado FROM consulta.pagos GROUP BY mes ORDER BY "
        'mes", "interpretacion": "Total abonado por mes, segun la fecha en que '
        'entro el dinero"}',
    ),
    (
        "¿Que cuotas estan vencidas hoy?",
        '{"tipo": "consulta", "sql": "SELECT unidad_codigo, periodo, saldo FROM '
        "consulta.cuotas WHERE saldo > 0 AND fecha_vencimiento < "
        'consulta.fecha_corte() ORDER BY saldo DESC", "interpretacion": "Cuotas '
        'con saldo cuyo vencimiento es anterior a la fecha de corte"}',
    ),
    (
        "¿Quienes son los mejores propietarios?",
        '{"tipo": "ambigua", "pregunta": "\\"Mejores\\" admite varias lecturas y '
        'cada una da un resultado distinto. ¿Cual quieres?", "opciones": ['
        '{"id": "a", "texto": "Los que mas han pagado en total", "sql": "SELECT '
        "u.propietario_nombre, SUM(p.valor) AS pagado FROM consulta.pagos p JOIN "
        "consulta.unidades u ON u.codigo = p.unidad_codigo GROUP BY "
        'u.propietario_nombre ORDER BY pagado DESC"}, '
        '{"id": "b", "texto": "Los que no deben nada", "sql": "SELECT '
        "u.propietario_nombre, SUM(c.saldo) AS deuda FROM consulta.cuotas c JOIN "
        "consulta.unidades u ON u.codigo = c.unidad_codigo GROUP BY "
        'u.propietario_nombre HAVING SUM(c.saldo) = 0"}, '
        '{"id": "c", "texto": "Los mas antiguos", "sql": "SELECT pr.nombre, '
        "pr.fecha_alta FROM consulta.propietarios pr ORDER BY pr.fecha_alta\"}]}",
    ),
    (
        "¿Cuantas PQRS hay abiertas?",
        '{"tipo": "sin_datos", "falta": "peticiones, quejas y reclamos", '
        '"disponibles": ["unidades", "propietarios", "cuotas", "pagos"]}',
    ),
]


def _bloque_ejemplos() -> str:
    partes = ["EJEMPLOS:"]
    for pregunta, respuesta in _PARES:
        partes.append(f"\nPregunta: {pregunta}\nRespuesta: {respuesta}")
    return "\n".join(partes)


def construir(catalogo: dict[str, Any], *, con_instrucciones: bool = True) -> str:
    """El contexto completo, sin la pregunta.

    `con_instrucciones=False` borra el bloque 1 —el papel y el formato— y deja
    solo el material. **Es lo que usa T-4**: si con el bloque anulado el
    guardian sigue rechazando exactamente lo mismo, la contencion no depende
    del texto que se le manda al modelo. Es CD1 convertido en prueba, y por eso
    el parametro vive aqui y no en el fichero de pruebas: una prueba que
    construyera su propio prompt reducido estaria midiendo otro sistema.
    """
    bloques = []
    if con_instrucciones:
        bloques.append(_PAPEL)
    bloques += [
        _bloque_esquema(catalogo),
        _bloque_reglas(catalogo),
        _bloque_valores(catalogo),
        _bloque_rangos(catalogo),
        _bloque_ausencias(catalogo),
    ]
    if con_instrucciones:
        bloques.append(_bloque_ejemplos())
    return "\n\n".join(bloques)
