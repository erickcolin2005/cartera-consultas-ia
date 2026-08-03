"""
generar.py — produce datos/04-datos.sql (D9).

QUE SE VERSIONA Y QUE NO
------------------------
El artefacto versionado que se carga al arrancar es `04-datos.sql`, NO este
script. Este script tambien se versiona, pero **no se ejecuta al arrancar**.

La razon esta escrita en `modelo-datos.md` §5.2 y no es teorica: un script con
semilla fija es determinista solo mientras no cambie la implementacion del
generador de aleatorios ni la version del interprete. Si cambia, los datos
cambian en silencio, los valores esperados dejan de coincidir y C1 se desploma
sin que nadie haya tocado el sistema. Es un fallo dificil de diagnosticar y
perfectamente evitable.

REGLA DE OPERACION (va al README)
---------------------------------
Si `04-datos.sql` cambia, `valores-esperados.md` se recalcula y la tabla de
resultados del banco se vuelve a medir **en el mismo commit**.

QUE GARANTIZA ESTE GENERADOR
----------------------------
RN-01 a RN-07 y la composicion dirigida de `modelo-datos.md` §5.3: los datos se
diseñan, no se sortean. Cada hecho garantizado esta marcado con el caso del
banco que lo necesita.

USO
---
    python datos/generar.py            # reescribe datos/04-datos.sql
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# ---------------------------------------------------------------------------
# Constantes de dominio
# ---------------------------------------------------------------------------

SEMILLA = 20260727

# RN-07 · fecha de corte fija y versionada. "Hoy" significa siempre este dia.
FECHA_CORTE = date(2026, 7, 5)

PERIODO_INICIAL = date(2025, 1, 1)
PERIODO_FINAL = date(2026, 7, 1)          # 19 periodos

DIA_VENCIMIENTO = 10                       # RN-02 · emision el 1, vencimiento el 10

# La derrama extraordinaria: reposicion de los ascensores de las torres A y B.
# Se cobra solo a los apartamentos de esas dos torres — locales y parqueaderos
# no usan ascensor. Es la regla de dominio que hace que "facturado" no sea solo
# administracion (A-02, N-09).
PERIODO_DERRAMA = date(2025, 9, 1)
VENCIMIENTO_DERRAMA = date(2025, 10, 15)
MONTO_DERRAMA = Decimal("96000000")

PRESUPUESTO_MENSUAL = {2025: Decimal("42000000"), 2026: Decimal("45500000")}

# Rango declarado en catalogo.yaml §7.2. Ningun pago cae fuera.
PAGO_MIN = date(2025, 1, 10)
PAGO_MAX = date(2026, 7, 4)

MEDIOS_PAGO = ["transferencia", "pse", "efectivo", "cheque"]

# Centinelas de T-5: prueba de fuga de datos al modelo. Son improbables a
# proposito — si alguno aparece en el texto enviado al proveedor, la fuga es
# inequivoca y no admite explicacion alternativa.
NOMBRE_CENTINELA = "Vercingetorix Qhuazbal Ñemerov"
REFERENCIA_CENTINELA = "CENTINELA-QX7Z-4M91"

NOMBRES = [
    "Adriana", "Alberto", "Alejandra", "Andres", "Angela", "Antonio", "Beatriz",
    "Camilo", "Carolina", "Cesar", "Claudia", "Daniel", "Diana", "Eduardo",
    "Elena", "Esteban", "Fabian", "Fernanda", "Gabriel", "Gloria", "Gustavo",
    "Helena", "Hernando", "Ignacio", "Isabel", "Javier", "Jimena", "Jorge",
    "Juliana", "Leonardo", "Lorena", "Manuel", "Marcela", "Mauricio", "Natalia",
    "Nicolas", "Olga", "Oscar", "Patricia", "Rafael", "Rocio", "Rodrigo",
    "Sandra", "Sebastian", "Silvia", "Tomas", "Valentina", "Wilson",
]

APELLIDOS = [
    "Acosta", "Aguirre", "Alvarez", "Arango", "Bermudez", "Bustos", "Caicedo",
    "Cardenas", "Castaño", "Cordoba", "Duarte", "Escobar", "Forero", "Galvis",
    "Gaviria", "Guerrero", "Higuita", "Hurtado", "Jaramillo", "Lozano",
    "Mendoza", "Montoya", "Naranjo", "Ocampo", "Ospina", "Palacios", "Pardo",
    "Quintero", "Restrepo", "Rincon", "Salazar", "Sarmiento", "Tovar",
    "Urrego", "Valencia", "Vargas", "Velasquez", "Zapata", "Zuluaga", "Bejarano",
    "Cifuentes", "Delgado", "Espinosa", "Franco", "Gutierrez", "Herrera",
    "Idarraga", "Lemus",
]


def dinero(valor: Decimal) -> Decimal:
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def a_centena(valor: Decimal) -> Decimal:
    """Los recibos de una copropiedad no llevan centavos sueltos."""
    return (valor / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 100


def periodos() -> list[date]:
    salida, actual = [], PERIODO_INICIAL
    while actual <= PERIODO_FINAL:
        salida.append(actual)
        anio, mes = actual.year, actual.month + 1
        if mes == 13:
            anio, mes = anio + 1, 1
        actual = date(anio, mes, 1)
    return salida


def esc(texto: str) -> str:
    return texto.replace("'", "''")


# ---------------------------------------------------------------------------
# Generacion
# ---------------------------------------------------------------------------

def generar() -> str:
    rnd = random.Random(SEMILLA)
    lista_periodos = periodos()

    # --- propietarios (48) ------------------------------------------------
    propietarios = []
    usados: set[str] = set()
    for i in range(1, 49):
        while True:
            nombre = f"{NOMBRES[(i * 7) % len(NOMBRES)]} {APELLIDOS[(i * 11) % len(APELLIDOS)]}"
            if nombre not in usados:
                break
            i += 1  # colision: se desplaza el indice, sigue siendo determinista
        usados.add(nombre)
        propietarios.append(nombre)

    # Un propietario lleva el nombre centinela de T-5.
    propietarios[23] = NOMBRE_CENTINELA

    filas_propietarios = []
    for idx, nombre in enumerate(propietarios, start=1):
        documento = str(10_000_000 + rnd.randrange(0, 89_000_000))
        base_correo = (
            nombre.lower()
            .replace(" ", ".")
            .replace("ñ", "n").replace("á", "a").replace("é", "e")
            .replace("í", "i").replace("ó", "o").replace("ú", "u")
        )
        # dominio .test: reservado por la IANA, no puede existir. Ningun correo
        # sintetico de este conjunto puede alcanzar a una persona real.
        email = f"{base_correo}{idx}@ejemplo.test"
        telefono = f"+57 3{rnd.randrange(0, 10)}{rnd.randrange(0, 10)} {rnd.randrange(100, 1000)} {rnd.randrange(1000, 10000)}"
        fecha_alta = date(2018, 1, 1) + timedelta(days=rnd.randrange(0, 2525))
        filas_propietarios.append((idx, nombre, documento, email, telefono, fecha_alta))

    # --- unidades (60) ----------------------------------------------------
    # 54 apartamentos + 4 locales + 2 parqueaderos, 20 por torre.
    # Los codigos son unicos en toda la copropiedad: '302' y '101' existen
    # porque N-05, M-03, N-08 y M-04 los nombran.
    unidades: list[dict] = []
    plantilla_apartamentos = {
        "A": [f"{piso}0{apto}" for piso in range(1, 7) for apto in (1, 2, 3)],
        "B": [f"{piso}0{apto}" for piso in range(1, 7) for apto in (4, 5, 6)],
        "C": [f"{piso}0{apto}" for piso in range(1, 7) for apto in (7, 8, 9)],
    }
    for torre in ("A", "B", "C"):
        for codigo in plantilla_apartamentos[torre]:
            unidades.append({
                "codigo": codigo, "torre": torre, "tipo": "apartamento",
                "area": Decimal(rnd.randrange(5500, 9500)) / 100,
            })
    for codigo, torre in (("L-01", "A"), ("L-02", "B"), ("L-03", "B"), ("L-04", "C")):
        unidades.append({
            "codigo": codigo, "torre": torre, "tipo": "local",
            "area": Decimal(rnd.randrange(3000, 6000)) / 100,
        })
    for codigo, torre in (("P-01", "A"), ("P-02", "C")):
        unidades.append({
            "codigo": codigo, "torre": torre, "tipo": "parqueadero",
            "area": Decimal(rnd.randrange(1200, 1500)) / 100,
        })

    area_total = sum(u["area"] for u in unidades)
    acumulado = Decimal("0")
    for u in unidades[:-1]:
        u["coeficiente"] = (u["area"] / area_total).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        acumulado += u["coeficiente"]
    unidades[-1]["coeficiente"] = Decimal("1.000000") - acumulado   # suma exacta 1

    # RN-06 · 1:N. 38 propietarios con una unidad, 8 con dos, 2 con tres.
    # -> 10 propietarios con mas de una unidad, que es lo que mide N-10.
    reparto = [3, 3] + [2] * 8 + [1] * 38
    duenos: list[int] = []
    for propietario_id, cuantas in enumerate(reparto, start=1):
        duenos.extend([propietario_id] * cuantas)
    orden = list(range(len(unidades)))
    rnd.shuffle(orden)
    for posicion, indice_unidad in enumerate(orden):
        unidades[indice_unidad]["propietario_id"] = duenos[posicion]

    for numero, u in enumerate(unidades, start=1):
        u["id"] = numero
    por_codigo = {u["codigo"]: u for u in unidades}

    # --- cuotas -----------------------------------------------------------
    cuotas: list[dict] = []
    siguiente_id = 1
    for u in unidades:
        for periodo in lista_periodos:
            valor = a_centena(dinero(u["coeficiente"] * PRESUPUESTO_MENSUAL[periodo.year]))
            cuotas.append({
                "id": siguiente_id, "unidad_id": u["id"], "periodo": periodo,
                "concepto": "administracion", "valor": valor,
                "emision": periodo, "vencimiento": periodo.replace(day=DIA_VENCIMIENTO),
            })
            siguiente_id += 1

    afectadas = [u for u in unidades if u["tipo"] == "apartamento" and u["torre"] in ("A", "B")]
    coef_afectadas = sum(u["coeficiente"] for u in afectadas)
    for u in afectadas:
        valor = a_centena(dinero(u["coeficiente"] / coef_afectadas * MONTO_DERRAMA))
        cuotas.append({
            "id": siguiente_id, "unidad_id": u["id"], "periodo": PERIODO_DERRAMA,
            "concepto": "extraordinaria", "valor": valor,
            "emision": PERIODO_DERRAMA, "vencimiento": VENCIMIENTO_DERRAMA,
        })
        siguiente_id += 1

    cuotas_por_unidad: dict[int, list[dict]] = {u["id"]: [] for u in unidades}
    for c in cuotas:
        cuotas_por_unidad[c["unidad_id"]].append(c)
    for lista in cuotas_por_unidad.values():
        lista.sort(key=lambda c: (c["vencimiento"], c["id"]))

    # --- perfiles de pago -------------------------------------------------
    # Los datos se diseñan: hacen falta unidades con 1, 2, 3 y mas de 6 meses
    # de mora para que las tres opciones de A-03 den listas DISTINTAS. Si todas
    # dieran la misma lista, la repregunta seria teatro.
    perfiles = (
        ["al_dia"] * 20 + ["esporadico"] * 9 + ["atraso_1"] * 8 + ["atraso_2"] * 7
        + ["atraso_3"] * 6 + ["atraso_7"] * 5 + ["cronico"] * 4 + ["parcial"] * 1
    )
    assert len(perfiles) == len(unidades)
    ids_barajados = [u["id"] for u in unidades]
    rnd.shuffle(ids_barajados)
    perfil_de = dict(zip(ids_barajados, perfiles))

    # La unidad 101 debe tener pagos en 2026 (N-08) y la 302 debe ser
    # consultable con su propietario (N-05, M-03). Se fuerza el perfil.
    for codigo_forzado in ("101", "302", "205"):
        perfil_de[por_codigo[codigo_forzado]["id"]] = "al_dia"

    # --- pagos ------------------------------------------------------------
    pagos: list[dict] = []
    id_pago = 1
    contador_giro = 0

    def fecha_de_pago(cuota: dict, retraso_dias: int = 0) -> date:
        base = cuota["vencimiento"] + timedelta(days=rnd.randrange(-8, 7) + retraso_dias)
        limite_inferior = max(PAGO_MIN, cuota["emision"])
        return min(max(base, limite_inferior), PAGO_MAX)

    for u in unidades:
        perfil = perfil_de[u["id"]]
        lista = cuotas_por_unidad[u["id"]]
        vencidas = [c for c in lista if c["vencimiento"] < FECHA_CORTE]
        corrientes = [c for c in lista if c["vencimiento"] >= FECHA_CORTE]

        impagas: set[int] = set()
        parciales: set[int] = set()
        if perfil == "esporadico":
            candidatas = vencidas[: max(1, len(vencidas) // 2)]
            impagas = {c["id"] for c in rnd.sample(candidatas, 2)}
        elif perfil == "atraso_1":
            impagas = {vencidas[-1]["id"]}
        elif perfil == "atraso_2":
            impagas = {c["id"] for c in vencidas[-2:]}
        elif perfil == "atraso_3":
            impagas = {c["id"] for c in vencidas[-3:]}
        elif perfil == "atraso_7":
            impagas = {c["id"] for c in vencidas[-7:]}
        elif perfil == "cronico":
            impagas = {c["id"] for c in vencidas[-9:]}
            impagas |= {c["id"] for c in rnd.sample(vencidas[:-9], 3)}
        elif perfil == "parcial":
            parciales = {vencidas[-2]["id"]}

        # Un giro agrupa varios abonos: misma fecha_pago y misma referencia
        # (RN-05). GROUP BY referencia recupera el hecho de que fue uno solo.
        pagables = [c for c in vencidas if c["id"] not in impagas]
        indice = 0
        while indice < len(pagables):
            agrupar = 1
            if rnd.random() < 0.18 and indice + 2 < len(pagables):
                agrupar = rnd.choice([2, 3])
            grupo = pagables[indice:indice + agrupar]
            indice += agrupar

            contador_giro += 1
            referencia = f"G-{grupo[-1]['vencimiento']:%Y%m}-{contador_giro:05d}"
            fecha = fecha_de_pago(grupo[-1])
            medio = rnd.choice(MEDIOS_PAGO)

            for c in grupo:
                proporcion = Decimal("0.6") if c["id"] in parciales else Decimal("1")
                pagos.append({
                    "id": id_pago, "cuota_id": c["id"], "fecha_pago": fecha,
                    "valor": a_centena(dinero(c["valor"] * proporcion)),
                    "medio_pago": medio, "referencia": referencia,
                })
                id_pago += 1

        # La cuota del periodo en curso esta emitida y aun no vencida (RN-02).
        # Que una parte este pagada y otra no es lo que mantiene viva la
        # ambiguedad de A-05: "¿cuanto se debe?" incluye o no lo corriente.
        if perfil in ("al_dia", "esporadico") and rnd.random() < 0.55:
            for c in corrientes:
                contador_giro += 1
                pagos.append({
                    "id": id_pago, "cuota_id": c["id"],
                    "fecha_pago": min(PAGO_MAX, max(PAGO_MIN, c["emision"] + timedelta(days=rnd.randrange(0, 4)))),
                    "valor": c["valor"], "medio_pago": rnd.choice(MEDIOS_PAGO),
                    "referencia": f"G-{c['periodo']:%Y%m}-{contador_giro:05d}",
                })
                id_pago += 1

    pago_por_cuota: dict[int, list[dict]] = {}
    for p in pagos:
        pago_por_cuota.setdefault(p["cuota_id"], []).append(p)

    # A-04 · hace falta un pago de julio de 2026 aplicado a una cuota de mayo,
    # para que las dos lecturas ("cuando entro el dinero" vs "a que mes
    # corresponde") den resultados distintos. Sin este hecho, A-04 es ambigua
    # en el enunciado pero no en los datos, y la repregunta no se puede
    # justificar con numeros.
    unidad_a04 = por_codigo["205"]
    cuota_mayo = next(
        c for c in cuotas_por_unidad[unidad_a04["id"]]
        if c["periodo"] == date(2026, 5, 1) and c["concepto"] == "administracion"
    )
    for p in pago_por_cuota[cuota_mayo["id"]]:
        p["fecha_pago"] = date(2026, 7, 2)
        p["referencia"] = f"G-202607-{contador_giro + 1:05d}"

    # Centinela de referencia (T-5).
    pagos[len(pagos) // 3]["referencia"] = REFERENCIA_CENTINELA

    # --- invariante RN-05: el saldo nunca es negativo ---------------------
    valor_de_cuota = {c["id"]: c["valor"] for c in cuotas}
    for cuota_id, lista_pagos in pago_por_cuota.items():
        assert sum(p["valor"] for p in lista_pagos) <= valor_de_cuota[cuota_id], (
            f"RN-05 violada en la cuota {cuota_id}: los pagos superan el valor facturado"
        )
    for p in pagos:
        assert PAGO_MIN <= p["fecha_pago"] <= PAGO_MAX, (
            f"pago {p['id']} fuera del rango declarado en catalogo.yaml §7.2"
        )

    return render(filas_propietarios, unidades, cuotas, pagos)


# ---------------------------------------------------------------------------
# Volcado
# ---------------------------------------------------------------------------

def render(propietarios, unidades, cuotas, pagos) -> str:
    partes: list[str] = []
    partes.append(
        "-- =====================================================================\n"
        "-- 04-datos.sql — GENERADO por datos/generar.py (semilla 20260727).\n"
        "-- NO SE EDITA A MANO. Este fichero ES el dato (D9): lo que se carga al\n"
        "-- arrancar es este volcado, no el generador.\n"
        "--\n"
        "-- Si este fichero cambia, `valores-esperados.md` se recalcula y la tabla\n"
        "-- de resultados del banco se vuelve a medir EN EL MISMO COMMIT.\n"
        f"-- Filas: {len(propietarios)} propietarios · {len(unidades)} unidades · "
        f"{len(cuotas)} cuotas · {len(pagos)} pagos.\n"
        "-- =====================================================================\n"
    )

    def volcar(tabla: str, columnas: str, filas: list[str]) -> None:
        partes.append(f"\nINSERT INTO {tabla} ({columnas}) VALUES")
        for i in range(0, len(filas), 100):
            trozo = filas[i:i + 100]
            partes.append(",\n".join(trozo) + (";" if i + 100 >= len(filas) else ";\n\nINSERT INTO "
                                               f"{tabla} ({columnas}) VALUES"))

    volcar(
        "cartera.propietarios", "id, nombre, documento, email, telefono, fecha_alta",
        [f"  ({i}, '{esc(n)}', '{d}', '{esc(e)}', '{t}', DATE '{f}')"
         for i, n, d, e, t, f in propietarios],
    )
    volcar(
        "cartera.unidades", "id, codigo, torre, tipo, area_m2, coeficiente, propietario_id",
        [f"  ({u['id']}, '{u['codigo']}', '{u['torre']}', '{u['tipo']}', {u['area']}, "
         f"{u['coeficiente']}, {u['propietario_id']})" for u in unidades],
    )
    volcar(
        "cartera.cuotas",
        "id, unidad_id, periodo, concepto, valor, fecha_emision, fecha_vencimiento",
        [f"  ({c['id']}, {c['unidad_id']}, DATE '{c['periodo']}', '{c['concepto']}', "
         f"{c['valor']}, DATE '{c['emision']}', DATE '{c['vencimiento']}')" for c in cuotas],
    )
    volcar(
        "cartera.pagos", "id, cuota_id, fecha_pago, valor, medio_pago, referencia",
        [f"  ({p['id']}, {p['cuota_id']}, DATE '{p['fecha_pago']}', {p['valor']}, "
         f"'{p['medio_pago']}', '{esc(p['referencia'])}')" for p in pagos],
    )
    partes.append("\n")
    return "".join(partes)


if __name__ == "__main__":
    destino = Path(__file__).with_name("04-datos.sql")
    contenido = generar()
    destino.write_text(contenido, encoding="utf-8")
    print(f"escrito {destino} ({len(contenido.splitlines())} lineas)")
