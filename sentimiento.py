#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de categoría — sistema de NLP sobre los comentarios del público.

===========================================================================
POR QUÉ ESTÁ DISEÑADO ASÍ
===========================================================================

El problema no es "sacar el sentimiento". Es sacar algo ACCIONABLE.

Saber que el 23% de los comentarios del BSE son negativos no sirve para nada:
no te dice qué hacer el lunes. Lo que sirve es saber que el 60% de esa negatividad
son DEMORAS EN SINIESTROS mientras que la de Mapfre es PRECIO. Eso sí es estrategia.
Por eso el clasificador no devuelve solo sentimiento: devuelve MOTIVO.

El sistema tiene cuatro etapas, y cada una existe por una razón concreta.

--- Etapa 1: filtro de ruido (reglas, sin IA) -----------------------------
La mayoría de los comentarios de Instagram no son opinión: son emojis sueltos,
gente etiquetando a un amigo, spam de "compra seguidores", bots. Mandárselos a un
modelo es pagar por clasificar basura y además ensuciar el promedio.
Se filtran con reglas baratas ANTES del LLM. Típicamente cae 40-60% del volumen.
Esta etapa es la que más mejora precisión y costo a la vez.

--- Etapa 2: clasificación con Claude -------------------------------------
Por qué un LLM y no un modelo de sentimiento español entrenado (pysentimiento, VADER,
etc.): esos están entrenados con tuits genéricos y se rompen con (a) español rioplatense,
(b) ironía —"excelente el servicio, solo 3 meses para pagarme" es NEGATIVO y cualquier
lexicón lo lee positivo—, y (c) jerga de seguros, donde "me rechazaron el siniestro"
tiene una carga que ninguna palabra sola delata. Claude maneja las tres.

Se pide salida estructurada con enum cerrado (no texto libre), en lotes indexados,
para que cada resultado vuelva a su comentario sin ambigüedad.

--- Etapa 3: validación --------------------------------------------------
Un clasificador que no medís es un clasificador en el que no podés confiar.
Dos controles:
  a) Estabilidad: se reclasifica una muestra en una segunda pasada independiente
     (otro orden, sin ver la etiqueta anterior) y se mide el acuerdo entre pasadas.
     Si baja del 85%, las etiquetas son ruidosas y el script te lo grita.
  b) Auditoría humana: escribe raw/auditoria_muestra.csv con 60 comentarios y su
     etiqueta, para que una persona los lea. NADIE debería presentar un número de
     sentimiento que no auditó con los ojos. Este archivo existe para eso.

--- Etapa 4: agregación (la hace analyze.py) ------------------------------
Sentimiento neto por marca, tasa de queja, y ranking de motivos — BSE contra la categoría.

===========================================================================
SESGOS QUE HAY QUE DECLARAR (y que el tablero declara)
===========================================================================
1. Los comentarios públicos SOBRE-EXPRESAN la queja. El que está contento con su
   póliza no comenta; al que le rebotaron un siniestro sí. El nivel absoluto NO es
   "la opinión del público uruguayo".
2. Las marcas MODERAN: borran comentarios. Lo que sobrevive está sesgado a positivo.
   Ojo que este sesgo empuja en dirección contraria al anterior, y no se cancelan
   de forma prolija.
   => Conclusión: estos números sirven para COMPARAR marcas entre sí y motivos entre
   sí, con el mismo sesgo aplicado a todos. No sirven como termómetro de satisfacción.
   El tablero lo dice explícitamente. Si alguien lo presenta como "el X% de los
   uruguayos está insatisfecho con el BSE", lo está usando mal.

Cómo se corre
-------------
    export ANTHROPIC_API_KEY=sk-ant-xxx
    python3 sentimiento.py               # clasifica
    python3 sentimiento.py --validar     # además mide estabilidad (2ª pasada)
    python3 sentimiento.py --modelo claude-haiku-4-5   # más barato, algo menos fino
"""

import os, sys, json, re, csv, random, argparse, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "raw")
CONFIG_PATH = os.path.join(HERE, "monitor.config.json")

sys.path.insert(0, HERE)
import config_local
config_local.cargar()   # lee el .env: las keys se configuran una vez

LOTE = 60           # comentarios por llamada
MUESTRA_VALID = 60  # comentarios para la validación / auditoría


# ══════════════════════════════════════════════════ Etapa 1: filtro de ruido

# Spam clásico de IG. Ojo: NO se filtra "sorteo"/"promo" a secas, porque las marcas
# hacen sorteos y esos comentarios sí son conversación real sobre la marca.
SPAM = re.compile(
    r"(seguidores?\s+(gratis|reales)|comprar?\s+seguidores|followers?\s+free|"
    r"link\s+en\s+(la\s+)?bio|escríbeme\s+al\s+priv|invertir?\s+en\s+(cripto|bitcoin)|"
    r"gana(r)?\s+dinero|whatsapp\s*\+?\d{6,}|t\.me/|bit\.ly/)", re.I)

SOLO_MENCIONES = re.compile(r"^(\s*@[\w.]+\s*)+$")
TIENE_LETRAS = re.compile(r"[a-záéíóúñü]{2,}", re.I)


def es_ruido(texto):
    """Devuelve el motivo por el que el comentario NO es opinión, o None si sí lo es."""
    t = texto.strip()
    if SOLO_MENCIONES.match(t):
        return "etiqueta a alguien"      # "@juan mirá esto" — no opina, reenvía
    if not TIENE_LETRAS.search(t):
        return "solo emojis/símbolos"    # "🔥🔥🔥" — es una reacción, no una opinión
    if SPAM.search(t):
        return "spam"
    if len(TIENE_LETRAS.sub("", t)) >= 0 and len(t) < 4:
        return "muy corto"
    return None


def filtrar(comentarios):
    limpios, descartados = [], collections.Counter()
    vistos = set()
    for c in comentarios:
        motivo = es_ruido(c["texto"])
        if motivo:
            descartados[motivo] += 1
            continue
        # Dedupe: el mismo texto repetido muchas veces es bot o copypaste.
        clave = (c["marca"], c["texto"].lower().strip())
        if clave in vistos:
            descartados["duplicado"] += 1
            continue
        vistos.add(clave)
        limpios.append(c)
    return limpios, descartados


# ══════════════════════════════════════════════════ Etapa 2: clasificación

SISTEMA = """Sos analista de reputación de marca en Uruguay, especializado en seguros.
Clasificás comentarios que el público dejó en posteos de aseguradoras.

Tené en cuenta:
- Español rioplatense, con voseo, ironía y sarcasmo. "Excelente, solo 3 meses para
  pagarme" es NEGATIVO, no positivo. Leé la intención, no las palabras sueltas.
- Muchos comentarios no hablan de la marca (charla entre usuarios, comentarios sobre
  un jugador de fútbol en un posteo de patrocinio, chistes). Esos van con relevante=false:
  no ensucian el sentimiento de la marca.
- Una pregunta ("¿cubre granizo?") es neutra y relevante: es interés, no queja.
- El motivo importa más que el sentimiento. Sé preciso ahí.

Devolvés exactamente un ítem por comentario, con el índice 'i' que te dieron."""


def clasificar(comentarios, cfg, modelo, mezclar=False):
    """Devuelve {indice_global: etiqueta}. Nunca revienta: si un lote falla, sigue."""
    import anthropic
    client = anthropic.Anthropic()
    motivos = cfg["comentarios"]["motivos"]

    schema = {
        "type": "object",
        "properties": {"c": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "i": {"type": "integer"},
                "relevante": {"type": "boolean"},
                "sentimiento": {"type": "string", "enum": ["positivo", "neutro", "negativo"]},
                "motivo": {"type": "string", "enum": motivos},
                "intensidad": {"type": "integer", "enum": [1, 2, 3]},
            },
            "required": ["i", "relevante", "sentimiento", "motivo", "intensidad"],
            "additionalProperties": False,
        }}},
        "required": ["c"],
        "additionalProperties": False,
    }

    orden = list(range(len(comentarios)))
    if mezclar:
        random.shuffle(orden)   # 2ª pasada: otro orden, para que el contexto del lote no arrastre

    etiquetas, fallos = {}, 0
    for ini in range(0, len(orden), LOTE):
        idxs = orden[ini:ini + LOTE]
        listado = "\n".join(
            "%d [%s] %s" % (j, comentarios[g]["marca"],
                            comentarios[g]["texto"].replace("\n", " ")[:300])
            for j, g in enumerate(idxs))
        try:
            r = client.messages.create(
                model=modelo,
                max_tokens=8000,
                thinking={"type": "adaptive"},
                output_config={"effort": "low",
                               "format": {"type": "json_schema", "schema": schema}},
                system=SISTEMA,
                messages=[{"role": "user", "content":
                           "Motivos posibles: %s\n\nComentarios:\n%s" % (", ".join(motivos), listado)}],
            )
            txt = next(b.text for b in r.content if b.type == "text")
            for it in json.loads(txt)["c"]:
                j = it["i"]
                if 0 <= j < len(idxs):
                    etiquetas[idxs[j]] = it
        except Exception as e:
            fallos += 1
            print("  [aviso] lote %d falló: %s" % (ini // LOTE, e), file=sys.stderr)
        print("\r  clasificados %d/%d" % (len(etiquetas), len(orden)), end="", flush=True)
    print()
    if fallos:
        print("  [aviso] %d lote(s) fallaron: esos comentarios quedan sin etiqueta." % fallos,
              file=sys.stderr)
    return etiquetas


# ══════════════════════════════════════════════════ Etapa 3: validación

def validar(comentarios, etiquetas, cfg, modelo):
    """Segunda pasada independiente sobre una muestra: mide si el clasificador es estable."""
    idxs = [i for i in etiquetas if etiquetas[i].get("relevante")]
    if len(idxs) < 20:
        print("Muy pocos comentarios relevantes para validar.")
        return
    muestra = random.sample(idxs, min(MUESTRA_VALID, len(idxs)))
    sub = [comentarios[i] for i in muestra]

    print("\nValidando: segunda pasada sobre %d comentarios…" % len(sub))
    segundas = clasificar(sub, cfg, modelo, mezclar=True)

    ac_sent = sum(1 for j, i in enumerate(muestra)
                  if j in segundas and segundas[j]["sentimiento"] == etiquetas[i]["sentimiento"])
    ac_mot = sum(1 for j, i in enumerate(muestra)
                 if j in segundas and segundas[j]["motivo"] == etiquetas[i]["motivo"])
    n = sum(1 for j in range(len(muestra)) if j in segundas) or 1

    ps, pm = ac_sent / n * 100, ac_mot / n * 100
    print("\n  Acuerdo entre pasadas · sentimiento: %.0f%%   · motivo: %.0f%%  (n=%d)" % (ps, pm, n))
    if ps < 85:
        print("  ⚠  El sentimiento es INESTABLE (<85%). No presentes estos números sin revisar\n"
              "     la muestra a mano: raw/auditoria_muestra.csv", file=sys.stderr)
    else:
        print("  ✓  Sentimiento estable. Igual leé la muestra de auditoría antes de presentar.")
    if pm < 70:
        print("  ⚠  Los MOTIVOS son inestables (<70%): probablemente las categorías se solapan.\n"
              "     Revisá 'comentarios.motivos' en monitor.config.json.", file=sys.stderr)


def escribir_auditoria(comentarios, etiquetas):
    """La muestra que un humano tiene que leer antes de creerle al número."""
    idxs = list(etiquetas)
    random.shuffle(idxs)
    ruta = os.path.join(RAW_DIR, "auditoria_muestra.csv")
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["marca", "comentario", "relevante", "sentimiento", "motivo", "intensidad",
                    "¿coincidís? (sí/no)"])
        for i in idxs[:MUESTRA_VALID]:
            e, c = etiquetas[i], comentarios[i]
            w.writerow([c["marca"], c["texto"][:200], e["relevante"], e["sentimiento"],
                        e["motivo"], e["intensidad"], ""])
    print("\nMuestra de auditoría: %s" % ruta)
    print("   Abrila, leé 60 comentarios y marcá si coincidís. Es el único control real.")


# ══════════════════════════════════════════════════ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validar", action="store_true", help="2ª pasada para medir estabilidad")
    ap.add_argument("--modelo", default="claude-opus-4-8",
                    help="claude-opus-4-8 (default) | claude-haiku-4-5 (más barato)")
    args = ap.parse_args()

    ruta = os.path.join(RAW_DIR, "comments.jsonl")
    if not os.path.exists(ruta):
        print("ERROR: no hay raw/comments.jsonl. Corré primero fetch_comments.py", file=sys.stderr)
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: falta ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1
    try:
        import anthropic  # noqa: F401
    except ImportError:
        print("ERROR: falta el SDK. Corré:  pip3 install anthropic", file=sys.stderr)
        return 1

    cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    crudos = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]

    # Etapa 1
    comentarios, descartados = filtrar(crudos)
    print("Comentarios bajados : %d" % len(crudos))
    print("Ruido descartado    : %d" % sum(descartados.values()))
    for m, c in descartados.most_common():
        print("     %-22s %d" % (m, c))
    print("A clasificar        : %d  (%.0f%% del total)"
          % (len(comentarios), len(comentarios) / max(len(crudos), 1) * 100))
    if not comentarios:
        return 0

    # Etapa 2
    print("\nClasificando con %s…" % args.modelo)
    etiquetas = clasificar(comentarios, cfg, args.modelo)

    for i, e in etiquetas.items():
        comentarios[i].update({k: e[k] for k in
                               ("relevante", "sentimiento", "motivo", "intensidad")})

    salida = os.path.join(RAW_DIR, "comments_scored.jsonl")
    with open(salida, "w", encoding="utf-8") as f:
        for i, c in enumerate(comentarios):
            if i in etiquetas:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

    rel = [c for i, c in enumerate(comentarios) if i in etiquetas and c["relevante"]]
    sent = collections.Counter(c["sentimiento"] for c in rel)
    n = len(rel) or 1
    print("\nRelevantes (hablan de la marca): %d de %d" % (len(rel), len(etiquetas)))
    print("   positivo %3d (%2.0f%%) · neutro %3d (%2.0f%%) · negativo %3d (%2.0f%%)"
          % (sent["positivo"], sent["positivo"] / n * 100,
             sent["neutro"], sent["neutro"] / n * 100,
             sent["negativo"], sent["negativo"] / n * 100))

    # Etapa 3
    escribir_auditoria(comentarios, etiquetas)
    if args.validar:
        validar(comentarios, etiquetas, cfg, args.modelo)

    print("\nSiguiente paso:  python3 analyze.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
