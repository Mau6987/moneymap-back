"""Genera DICCIONARIO_CAMPOS.md desde la base de datos.

Uso:
    psql -d moneymap -At -f tools/dictionary.sql | python tools/build_dictionary.py > DICCIONARIO_CAMPOS.md

Las descripciones salen de los comentarios de migrations/990_comments.sql; la
estructura (tipos, claves, relaciones, triggers) sale de PostgreSQL. Así el
diccionario no se desactualiza: si cambia una migración, se vuelve a generar.
"""

import json
import re
import sys

MODULES = [
    (
        "iam",
        "Usuarios y acceso",
        "Quién es la persona y cómo entra: perfil, términos aceptados, personalización, formas de iniciar sesión, "
        "sesiones y dispositivos. Solo mayores de 18 años.",
    ),
    (
        "billing",
        "Planes y suscripciones",
        "Plan gratuito y planes de pago, precios mensual y anual, suscripciones de App Store y Google Play, pagos "
        "y límites por plan (tarjetas, monedas, metas, dictados). Sin suscripción con acceso, el usuario está en el gratuito.",
    ),
    (
        "catalog",
        "Datos de referencia",
        "Lo que comparten todos los usuarios y define el equipo: monedas, tipos de cuenta, grupos del Money Flow "
        "y categorías iniciales. Cambiarlo es un INSERT o UPDATE, sin desplegar código.",
    ),
    (
        "finance",
        "Núcleo financiero",
        "El dinero del usuario: configuración y periodo, Mis monedas, cuentas (efectivo y tarjetas), datos de tarjeta, "
        "categorías, recurrentes y transacciones. Cada cuenta tiene una moneda y nada se convierte; los saldos los "
        "mantiene la base de datos.",
    ),
    ("goals", "Metas de ahorro", "Metas con su moneda y sus aportes; alimentan el Goal Forecast y Safe to Spend."),
    (
        "planning",
        "Decisiones",
        "Historial de Can I Afford It?. Safe to Spend y What If? se calculan al momento y no se guardan.",
    ),
    (
        "reports",
        "Resúmenes",
        "Money Story semanal y mensual. Los totales del Money Flow y de efectivo o tarjeta se calculan al momento "
        "con funciones (ver la sección Funciones).",
    ),
    ("notify", "Notificaciones", "Tipos de aviso, lo que el usuario apagó y la bandeja de avisos enviados."),
    (
        "ai",
        "Registro por voz con IA",
        "Proveedores de IA con principal y respaldos, cada dictado, cada llamada con su costo y el uso por usuario.",
    ),
    (
        "ops",
        "Logs e incidentes",
        "Eventos importantes del sistema (solo inserción) e incidentes con su ciclo de vida. No guarda datos financieros.",
    ),
    ("core", "Infraestructura", "Auditoría de cambios y eventos pendientes de publicar (outbox)."),
]

ON_DELETE = {
    "c": "en cascada",
    "n": "si se borra, queda vacío",
    "r": None,
    "a": None,
    "d": "si se borra, toma el valor por defecto",
}


def friendly_type(col):
    t = col["type"]
    if col.get("enum"):
        return "lista fija: " + ", ".join(col["enum"])
    m = re.fullmatch(r"character\((\d+)\)", t)
    if m:
        return f"texto de {m.group(1)}"
    m = re.fullmatch(r"numeric\((\d+),(\d+)\)", t)
    if m:
        return f"decimal ({m.group(1)},{m.group(2)})"
    return {
        "uuid": "UUID",
        "text": "texto",
        "citext": "texto (sin distinguir mayúsculas)",
        "boolean": "sí/no",
        "date": "fecha",
        "timestamp with time zone": "fecha y hora",
        "jsonb": "JSON",
        "smallint": "entero",
        "integer": "entero",
        "bigint": "entero",
        "inet": "IP",
        "text[]": "lista de textos",
    }.get(t, t)


def friendly_default(d):
    if d is None:
        return "—"
    d = re.sub(r"::[a-z_ .]+(\[\])?", "", d).strip("'")
    return {
        "core.uuid_v7()": "UUID v7",
        "now()": "ahora",
        "CURRENT_DATE": "hoy",
        "true": "sí",
        "false": "no",
        "{}": "{}",
        "[]": "[]",
    }.get(d, d)


def keys_for(table):
    """Clave y relación de cada columna."""
    out = {c["name"]: [] for c in table["columns"]}
    pk = next((set(k["cols"]) for k in table["constraints"] if k["type"] == "p"), set())
    for k in table["constraints"]:
        cols = k["cols"] or []
        if k["type"] == "p":
            for c in cols:
                out[c].append("PK" if len(cols) == 1 else f"PK ({', '.join(cols)})")
        elif k["type"] == "u":
            # Las únicas que contienen la PK (user_id, id, currency…) solo existen para que
            # otras tablas apunten con una FK compuesta: no agregan nada al lector.
            if any(c not in out for c in cols) or (pk and pk <= set(cols)):
                continue
            where = f", si {k['where']}" if k.get("where") else ""
            label = "Única" if len(cols) == 1 else f"Única ({', '.join(cols)}{where})"
            if len(cols) == 1 and where:
                label = f"Única{where}"
            for c in cols:
                if label not in out[c]:
                    out[c].append(label)
        elif k["type"] == "f":
            ref_cols = k["ref_cols"]
            for c, rc in zip(cols, ref_cols):
                if c == "user_id" and len(cols) > 1:
                    continue  # el user_id de una FK compuesta solo asegura "del mismo usuario"
                extra = [x for x in cols if x not in (c, "user_id")]
                notes = []
                if extra:
                    notes.append("junto con " + ", ".join(extra))
                if "user_id" in cols and len(cols) > 1:
                    notes.append("del mismo usuario")
                if ON_DELETE.get(k["on_delete"]):
                    notes.append(ON_DELETE[k["on_delete"]])
                text = f"FK → {k['ref_table']}.{rc}" + (f" ({', '.join(notes)})" if notes else "")
                out[c].append(text)
    return {c: "; ".join(v) if v else "—" for c, v in out.items()}


def relations(table, all_tables):
    me = f"{table['schema']}.{table['name']}"
    points = sorted({k["ref_table"] for k in table["constraints"] if k["type"] == "f" and k["ref_table"] != me})
    used_by = sorted(
        {
            f"{t['schema']}.{t['name']}"
            for t in all_tables
            for k in t["constraints"]
            if k["type"] == "f" and k["ref_table"] == me and f"{t['schema']}.{t['name']}" != me
        }
    )
    lines = []
    if points:
        lines.append("- **Apunta a:** " + ", ".join(f"`{p}`" for p in points))
    if used_by:
        lines.append("- **La usan:** " + ", ".join(f"`{u}`" for u in used_by))
    return lines


def split_comment(comment):
    """Separa 'Quién escribe:' y 'Ejemplo:' del propósito."""
    if not comment:
        return "", None, None
    m = re.match(r"(.*?)(?:\s*Quién escribe:\s*(.*?))?(?:\s*Ejemplo:\s*(.*))?$", comment, re.S)
    return m.group(1).strip(), (m.group(2) or "").strip() or None, (m.group(3) or "").strip() or None


def cell(text):
    return (text or "—").replace("|", "\\|").replace("\n", " ")


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # en Windows la consola no usa UTF-8
    data = json.loads(sys.stdin.read())
    tables = data["tables"]
    by_schema = {}
    for t in tables:
        by_schema.setdefault(t["schema"], []).append(t)
    n_cols = sum(len(t["columns"]) for t in tables)

    o = []
    o += [
        "# Diccionario de datos · MoneyMap V1",
        "",
        f"**{len(tables)} tablas, {n_cols} campos y {len(data['views'] or [])} vistas** en {len(by_schema)} módulos. "
        "Este archivo se genera desde la base de datos (`tools/build_dictionary.py`), así que coincide con las migraciones.",
        "",
        "## Cómo leerlo",
        "",
        "- Cada tabla dice **para qué sirve**, **quién la escribe** (la API, un worker, el equipo o la base sola) y un **ejemplo**.",
        "- **Relaciones:** *Apunta a* = tablas de las que depende; *La usan* = tablas que dependen de ella.",
        "- **Lo que hace la base sola:** reglas y cálculos automáticos (triggers). La API no los repite.",
        "- **Obligatorio:** *Sí* = no puede quedar vacío; *Calculado* = lo calcula la base.",
        "- **Clave y relación:** PK = clave primaria. *FK → tabla.campo* = el valor debe existir allí. "
        "*Del mismo usuario* = la clave incluye user_id e impide usar datos de otra persona. "
        "*En cascada* = si se borra la fila relacionada, se borra esta. *Si se borra, queda vacío* = esta fila se conserva sin el enlace.",
        "- **Seguridad por filas (RLS):** en las tablas marcadas, cada usuario solo ve y cambia sus propias filas.",
        "- Los valores de estados y tipos (expense, active, debit_card…) se guardan en inglés; la app los muestra traducidos.",
        "",
        "## Glosario",
        "",
        "| Término | Qué significa |",
        "|---|---|",
        "| Moneda principal | La moneda que la app muestra primero. Nada se convierte: cada total va por moneda. |",
        "| Cuenta por defecto | La cuenta (efectivo o tarjeta) que la app propone primero al registrar un movimiento. Una por usuario. |",
        "| Periodo | Cómo agrupa el usuario su dinero: semanal, quincenal o mensual, desde el día que elija. |",
        "| Money Flow | Diagrama de a dónde se fue el dinero: Ingresos → Necesidades, Estilo de vida, Metas → Disponible. |",
        "| Safe to Spend | Cuánto puede gastar en el periodo: saldo − recurrentes pendientes − ahorro planificado − aportes a metas. |",
        "| Borrado lógico | La fila no se borra: se llena deleted_at y deja de mostrarse, pero queda para el historial. |",
        "| UUID v7 | Identificador único que además va ordenado por fecha de creación. |",
        "| Trigger | Regla que la base ejecuta sola al insertar, editar o borrar una fila. |",
        "",
        "## Módulos",
        "",
        "| Módulo | Tablas | Para qué |",
        "|---|---|---|",
    ]
    for code, title, intro in MODULES:
        if code in by_schema:
            o.append(
                f"| [{code} · {title}](#{code}--{title.lower().replace(' ', '-')}) | {len(by_schema[code])} | {intro.split('. ')[0].rstrip('.')}. |"
            )
    o.append("")

    for code, title, intro in MODULES:
        if code not in by_schema:
            continue
        o += [f"## {code} · {title}", "", intro, ""]
        for t in by_schema[code]:
            name = f"{t['schema']}.{t['name']}"
            purpose, writer, example = split_comment(t["comment"])
            o += [f"### {name}", "", purpose, ""]
            if writer:
                o.append(f"- **Quién la escribe:** {writer}")
            if example:
                o.append(f"- **Ejemplo:** {example}")
            o += relations(t, tables)
            flags = []
            if t["rls"]:
                flags.append("con seguridad por filas (RLS)")
            if t["partitioned"]:
                flags.append("particionada")
            if flags:
                o.append("- **Características:** " + ", ".join(flags))
            auto = [tr["comment"] for tr in t["triggers"] if tr["comment"]]
            if auto:
                o.append("- **Lo que hace la base sola:**")
                o += [f"  - {a}" for a in dict.fromkeys(auto)]
            o += [
                "",
                "| Campo | Tipo | Obligatorio | Por defecto | Qué guarda | Clave y relación |",
                "|---|---|---|---|---|---|",
            ]
            keys = keys_for(t)
            for c in t["columns"]:
                req = "Calculado" if c["generated"] else ("Sí" if c["notnull"] else "No")
                o.append(
                    f"| {c['name']} | {cell(friendly_type(c))} | {req} | {cell(friendly_default(c['default']))} "
                    f"| {cell(c['comment'])} | {cell(keys[c['name']])} |"
                )
            o.append("")

    o += [
        "## Listas fijas (ENUM)",
        "",
        "Valores que no cambian; la base no acepta otros.",
        "",
        "| Tipo | Valores | Qué significa |",
        "|---|---|---|",
    ]
    for e in data["enums"] or []:
        o.append(f"| `{e['name']}` | {', '.join(e['values'])} | {cell(e['comment'])} |")
    o += [
        "",
        "## Vistas",
        "",
        "No guardan datos: calculan al consultarlas y respetan la seguridad por filas de quien consulta.",
        "",
        "| Vista | Qué muestra |",
        "|---|---|",
    ]
    for v in data["views"] or []:
        o.append(f"| `{v['name']}` | {cell(v['comment'])} |")
    o += [
        "",
        "## Funciones",
        "",
        "Las que llama la API o los workers. Los nombres de parámetros están en las migraciones.",
        "",
        "| Función | Qué hace |",
        "|---|---|",
    ]
    for f in data["functions"] or []:
        o.append(f"| `{f['name']}` | {cell(f['comment'])} |")
    o += [
        "",
        "## Tablas futuras",
        "",
        "Están en `future/` y se aplican cuando cada funcionalidad entre al alcance; no forman parte de este diccionario hasta entonces.",
        "",
        "| Archivo | Qué agrega |",
        "|---|---|",
        "| `future/110_budgets.sql` | `planning.budgets`: presupuesto por categoría de gasto y moneda, y avisos de presupuesto (FTR-014, FTR-015) |",
        "| `future/120_scenarios.sql` | Escenarios guardados de What If? (FTR-011) |",
        "| `future/130_attachments.sql` | Comprobantes adjuntos y OCR (FTR-030) |",
        "| `future/140_insights.sql` | Insights y fugas de dinero (FTR-016, FTR-017) |",
        "",
    ]
    sys.stdout.write("\n".join(o))


if __name__ == "__main__":
    main()
