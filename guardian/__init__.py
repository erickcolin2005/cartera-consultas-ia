"""
guardian — la capa 3. PAQUETE SEPARADO Y PURO.

POR QUE ES UN PAQUETE APARTE — dos razones independientes
----------------------------------------------------------
1. La cobertura de pruebas se mide ACOTADA A ESTE PAQUETE. Un umbral de
   cobertura sobre todo el repositorio se sube escribiendo pruebas de cualquier
   cosa; acotado al guardian, mide lo unico que importa.
2. La capa 3 tiene que poder QUITARSE en una prueba. T-2 la sustituye por un
   guardian nulo y comprueba que las capas 1 y 2 bastan solas. Si estuviera
   enredado con la API o con el ejecutor, esa sustitucion no seria posible y la
   independencia de capas seria una afirmacion sin prueba.

LO QUE ESTE PAQUETE NO HACE, Y SE COMPRUEBA ESTRUCTURALMENTE (T-5)
------------------------------------------------------------------
No se conecta a nada. Sin red, sin base de datos, sin reloj, sin aleatoriedad,
sin ficheros. Ni un `open`, ni un `import socket`, ni un `datetime.now`. No es
una convencion de estilo: hay una prueba que lee el codigo fuente de este
paquete y rompe el build si aparece alguno.

Por eso el catalogo se le PASA ya cargado (`Catalogo.desde_dict`), en vez de
leerlo. Leer un fichero seria entrada/salida.

USO
---
    import yaml
    from guardian import Catalogo, veredicto

    catalogo = Catalogo.desde_dict(yaml.safe_load(open("catalogo.yaml")))
    v = veredicto("SELECT count(*) FROM unidades", catalogo)
    v.permitido        # True
    v.sql_a_ejecutar   # con la envoltura de limite ya puesta
    v.regla            # None si se permite; "S0".."S7" o "C1" si no
    v.eco              # la entrada LITERAL y COMPLETA, siempre

LAS REGLAS, EN SU ORDEN EXACTO DE EVALUACION
--------------------------------------------
    S6  consulta demasiado grande (ANTES de parsear, sobre la cadena cruda)
    S0  no entiendo esta consulta (fallo cerrado ante CUALQUIER excepcion)
    S1  una sola consulta por ejecucion
    S2  solo consulta, no modifica — sobre el ARBOL COMPLETO, no la raiz
    S3  fuera de lo que puedo consultar — relaciones, en cualquier nivel
    S4  funcion no permitida — lista blanca explicita
    S5  construccion o modificador no permitido — tipo, modificadores y
        autorreferencia de un elemento definido en la propia consulta
    S7  tipo de dato o nodo no reconocido
    C1  fecha de corte  ·  C2  limite propio contradictorio

S3, S4, S5 y S7 emiten EL MISMO mensaje. Es el requisito RF-12, no un descuido:
un texto distinto diria que mecanismo se toco. Solo difiere el identificador.

ALCANCE DE I-2' — ESTRICTO DE MAS, Y ES DELIBERADO
---------------------------------------------------
Se rechaza TODO `WITH`, TODA subconsulta y TODO identificador entrecomillado.
El sistema rechazara consultas legitimas. Levantar esas restricciones sin
perder contencion es I-3'; hacerlo antes de tener la contencion probada seria
el orden equivocado.
"""

from .catalogo import Catalogo
from .contrato import (
    LIMITE_FILAS,
    MENSAJES,
    TOPE_LONGITUD,
    Veredicto,
)
from .nucleo import veredicto

__all__ = [
    "Catalogo",
    "LIMITE_FILAS",
    "MENSAJES",
    "TOPE_LONGITUD",
    "Veredicto",
    "veredicto",
]
