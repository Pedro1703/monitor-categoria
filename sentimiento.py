#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de categoría — sistema de NLP sobre los comentarios del público.

===========================================================================
POR QUÉ ESTÁ DISEÑADO ASÍ
===========================================================================

El problema no es "sacar el sentimiento". Es sacar algo ACCIONABLE.

Saber que el 23% de los comentarios de una marca son negativos no sirve para nada:
no te dice qué hacer el lunes. Lo que sirve es saber que el 60% de esa negatividad
es de un motivo concreto (una demora, un cargo, una atención) mientras que la de su
competidor es PRECIO. Eso sí es estrategia. Por eso el clasificador no devuelve solo
sentimiento: devuelve MOTIVO.

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
lexicón lo lee positivo—, y (c) jerga del sector, donde una frase como "me rechazaron
el reclamo" tiene una carga que ninguna palabra sola delata. Claude maneja las tres.

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
Sentimiento neto por marca, tasa de queja, y ranking de motivos — la marca protagonista
contra el resto de la categoría.

===========================================================================
SESGOS QUE HAY QUE DECLARAR (y que el tablero declara)
===========================================================================
1. Los comentarios públicos SOBRE-EXPRESAN la queja. El que está contento con el
   servicio no comenta; al que le fue mal sí. El nivel absoluto NO es "la opinión del
   público".
2. Las marcas MODERAN: borran comentarios. Lo que sobrevive está sesgado a positivo.
   Ojo que este sesgo empuja en dirección contraria al anterior, y no se cancelan
   de forma prolija.
   => Conclusión: estos números sirven para COMPARAR marcas entre sí y motivos entre
   sí, con el mismo sesgo aplicado a todos. No sirven como termómetro de satisfacción.
   El tablero lo dice explícitamente. Si alguien lo presenta como "el X% del público
   está insatisfecho con la marca", lo está usando mal.

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
import costos
config_local.cargar()   # lee el .env: las keys se configuran una vez

# Precio por millón de tokens (Opus 4.8 / Haiku 4.5). Para registrar gasto REAL.
TARIFA = {"claude-opus-4-8": (5.0, 25.0), "claude-haiku-4-5": (1.0, 5.0)}

LOTE = 60           # comentarios por llamada
MUESTRA_VALID = 60  # comentarios para la validación / auditoría

# Motivo de los comentarios que RoBERTuito puntuó pero Claude no alcanzó a clasificar.
# Aparece como tal en el informe: es más honesto que repartirlos en categorías inventadas.
SIN_MOTIVO = "Sin clasificar"


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

# Motivos que valen para cualquier categoría: no se derivan, se agregan siempre.
# Los motivos ESPECÍFICOS del sector (la experiencia concreta con la empresa) se
# derivan por corrida en _derivar_motivos.
MOTIVOS_BASE = [
    "Contenido de la marca: error o incoherencia",
    "Debate sobre el tema del posteo",
    "Consulta o pregunta",
    "Apoyo o elogio a la marca",
    "Evento / patrocinio / sorteo",
    "No habla de la marca",
    "Otro",
]


def _sistema(categoria):
    """Prompt de clasificación, parametrizado por la categoría de la corrida.

    Da la regla de prioridad (la experiencia concreta gana) sin nombrar motivos de
    un sector puntual: los motivos específicos llegan en 'Motivos posibles'.
    """
    return """Sos analista de reputación de marca. Trabajás sobre la categoría: %s.
Clasificás comentarios que el público dejó en los posteos de las marcas de esa categoría.

SENTIMIENTO
- Español rioplatense, con voseo, ironía y sarcasmo. "Excelente, solo 3 meses para
  resolverme el trámite" es NEGATIVO, no positivo. Leé la intención, no las palabras sueltas.
- Una pregunta ("¿tienen sucursal en Salto?") es NEUTRA y relevante: es interés, no queja.
- Si el comentario no habla de la marca (charla entre usuarios, un chiste, un comentario
  sobre un jugador en un posteo de patrocinio), relevante=false: no ensucia el sentimiento.

MOTIVO — elegí SIEMPRE uno de la lista "Motivos posibles" que te paso. Aplicá esta regla
en orden y pará en la primera que corresponda:

1. ¿El comentario relata una EXPERIENCIA CONCRETA de esta persona con la empresa (un
   trámite, una compra, una atención, un precio, un problema, un reclamo, la app)?
   → el motivo es esa experiencia. Tiene prioridad SIEMPRE, aunque además elogie a la
     marca o hable del evento del posteo.
     Ej: "Gracias por el evento, aunque todavía espero que me resuelvan el reclamo"
         → el motivo de experiencia, no "Evento / patrocinio / sorteo".

2. ¿Es una pregunta o pedido de información?  → Consulta o pregunta.

3. ¿La crítica es al CONTENIDO del posteo en sí — la marca publicó un dato falso, se
   contradice, o la pieza está mal hecha?  → Contenido de la marca: error o incoherencia.

4. ¿Opina sobre el TEMA del posteo (el rubro, la coyuntura, la sociedad) sin criticar a
   la marca?  → Debate sobre el tema del posteo. Suele ser relevante=true y sentimiento
   neutro: es conversación, no queja contra la marca.

5. ¿No hay nada de lo anterior, y el comentario apoya/felicita a la marca en general
   o a su campaña?  → Apoyo o elogio a la marca.

6. ¿Habla del evento, patrocinio o sorteo que la marca auspicia?  → Evento / patrocinio / sorteo.

Usá 'Otro' lo menos posible: si te dan ganas de usarlo seguido, es que falta una categoría.

El motivo importa más que el sentimiento: es lo que se convierte en decisión. Sé preciso.

Devolvés exactamente un ítem por comentario, con el índice 'i' que te dieron.""" % categoria


def _muestra_estratificada(items, tope):
    """Hasta `tope` items repartidos parejo entre marcas (round-robin).

    Sin esto la inferencia queda dominada por la marca con más volumen: una muestra al
    azar casi no ve a las chicas y los motivos sesgan hacia la grande. Repartir por marca
    da una base representativa de la categoría entera.
    """
    porm = collections.defaultdict(list)
    for it in items:
        porm[it.get("marca", "?")].append(it)
    for v in porm.values():
        random.shuffle(v)
    out, marcas = [], list(porm)
    while len(out) < tope:
        agregado = False
        for m in marcas:
            if porm[m]:
                out.append(porm[m].pop())
                agregado = True
                if len(out) >= tope:
                    break
        if not agregado:
            break
    return out


def _derivar_motivos(client, categoria, comentarios):
    """Deriva los motivos de EXPERIENCIA propios del sector, mirando los comentarios.

    Es el análogo de _derivar_territorios en analyze.py: en vez de una lista fija de
    seguros ('Cobertura rechazada', etc.), pregunta cuáles son los temas concretos de la
    relación de la gente con estas marcas y les suma MOTIVOS_BASE (los genéricos). Devuelve
    la lista completa, o None si falla (ahí el caller usa la lista de config).
    """
    # Base ancha y balanceada por marca: hasta 400 comentarios repartidos parejo, para
    # que los motivos no salgan de la marca con más conversación. Cuanto más ve, más
    # estable el corte (antes eran 80 al azar — base demasiado frágil).
    muestra = _muestra_estratificada(comentarios, 400)
    listado = "\n".join("- [%s] %s" % (c.get("marca", "?"), (c["texto"] or "").replace("\n", " ")[:220])
                        for c in muestra)
    # Sin minItems/maxItems: la API solo acepta 0 o 1 en esos campos y rechaza el schema
    # entero (error 400). El rango 2-8 va pedido en el prompt y recortado abajo con [:8].
    schema = {"type": "object",
              "properties": {"motivos": {"type": "array", "items": {"type": "string"}}},
              "required": ["motivos"], "additionalProperties": False}
    try:
        r = client.messages.create(
            model="claude-opus-4-8", max_tokens=1000,
            thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            system=("Sos analista de reputación de marca. Dada una categoría y una muestra de "
                    "comentarios del público, definís los MOTIVOS DE EXPERIENCIA CONCRETA por los "
                    "que la gente habla (bien o mal) de estas marcas: los temas tangibles de su "
                    "relación con la empresa. Ej. en seguros: 'Cobertura rechazada / letra chica', "
                    "'Siniestro / demora en el pago', 'Atención al cliente'. Ej. en un banco: "
                    "'Comisiones y cargos', 'App / home banking', 'Atención en sucursal', 'Créditos "
                    "y tasas'. 2 a 8 motivos, nombres cortos, mutuamente distintos, en español. NO "
                    "incluyas motivos genéricos (consultas, elogios, eventos, debate): esos se "
                    "agregan aparte."),
            messages=[{"role": "user", "content":
                       "Categoría: %s\n\nMuestra de comentarios:\n%s" % (categoria, listado)}],
        )
        txt = next(b.text for b in r.content if b.type == "text")
        esp = [m.strip() for m in json.loads(txt)["motivos"] if m.strip()][:8]
        return esp + MOTIVOS_BASE if esp else None
    except Exception as e:
        print("  [aviso] no se pudieron derivar motivos (%s): se usa la lista de config." % e,
              file=sys.stderr)
        return None


def clasificar(comentarios, motivos, categoria, modelo, mezclar=False):
    """Devuelve {indice_global: etiqueta}. Nunca revienta: si un lote falla, sigue."""
    import anthropic
    client = anthropic.Anthropic()

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
    tok_in = tok_out = 0     # se registra el gasto REAL que reporta la API, no un estimado
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
                system=_sistema(categoria),
                messages=[{"role": "user", "content":
                           "Motivos posibles: %s\n\nComentarios:\n%s" % (", ".join(motivos), listado)}],
            )
            tok_in += r.usage.input_tokens
            tok_out += r.usage.output_tokens
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

    # Gasto real de esta clasificación, con los tokens que la propia API reportó.
    p_in, p_out = TARIFA.get(modelo, (5.0, 25.0))
    usd = tok_in * p_in / 1e6 + tok_out * p_out / 1e6
    if etiquetas:
        concepto = "clasif_haiku" if "haiku" in modelo else "clasif_opus"
        costos.registrar(concepto, len(etiquetas), usd,
                         "%d tok in · %d tok out · %s" % (tok_in, tok_out, modelo))
        print("  costo real: USD %.3f  (%d tokens in · %d out)" % (usd, tok_in, tok_out))
    return etiquetas


# ══════════════════════════════════════════════════ Etapa 3: validación

def validar(comentarios, etiquetas, motivos, categoria, modelo):
    """Segunda pasada independiente: mide si el clasificador es estable.

    MUESTREO ESTRATIFICADO, a propósito. Los negativos son ~15% del total, así que una
    muestra al azar de 60 agarra unos 9 y el acuerdo sobre ellos queda sin poder
    estadístico — justo sobre lo único que va al informe. Por eso se validan TODOS los
    negativos, más una muestra del resto para el número global.
    """
    idxs = [i for i in etiquetas if etiquetas[i].get("relevante")]
    if len(idxs) < 20:
        print("Muy pocos comentarios relevantes para validar.")
        return

    negs = [i for i in idxs if etiquetas[i]["sentimiento"] == "negativo"]
    resto = [i for i in idxs if i not in set(negs)]
    muestra = negs + random.sample(resto, min(MUESTRA_VALID, len(resto)))
    sub = [comentarios[i] for i in muestra]

    print("\nValidando: segunda pasada sobre %d comentarios…" % len(sub))
    segundas = clasificar(sub, motivos, categoria, modelo, mezclar=True)

    ac_sent = sum(1 for j, i in enumerate(muestra)
                  if j in segundas and segundas[j]["sentimiento"] == etiquetas[i]["sentimiento"])
    ac_mot = sum(1 for j, i in enumerate(muestra)
                 if j in segundas and segundas[j]["motivo"] == etiquetas[i]["motivo"])
    n = sum(1 for j in range(len(muestra)) if j in segundas) or 1

    # Los motivos de los NEGATIVOS se miden aparte: son los únicos que van al informe.
    # Un motivo positivo ambiguo ("gracias por el evento") no cambia ninguna decisión;
    # confundir un motivo de queja con otro sí.
    negs = [(j, i) for j, i in enumerate(muestra)
            if j in segundas and etiquetas[i]["sentimiento"] == "negativo"]
    ac_neg = sum(1 for j, i in negs if segundas[j]["motivo"] == etiquetas[i]["motivo"])
    n_neg = len(negs)

    ps, pm = ac_sent / n * 100, ac_mot / n * 100
    print("\n  Acuerdo entre pasadas")
    print("     sentimiento          : %.0f%%   (n=%d)" % (ps, n))
    print("     motivo (todos)       : %.0f%%   (n=%d)" % (pm, n))
    if n_neg:
        pneg = ac_neg / n_neg * 100
        print("     motivo de las QUEJAS : %.0f%%   (n=%d)  ← el que va al informe" % (pneg, n_neg))

    if ps < 85:
        print("  ⚠  El sentimiento es INESTABLE (<85%). No presentes estos números sin revisar\n"
              "     la muestra a mano: raw/auditoria_muestra.csv", file=sys.stderr)
    else:
        print("  ✓  Sentimiento estable. Igual leé la muestra de auditoría antes de presentar.")

    if n_neg and ac_neg / n_neg * 100 < 70:
        print("  ⚠  Los motivos de las QUEJAS son inestables (<70%): las categorías se solapan.\n"
              "     Revisá 'comentarios.motivos' en monitor.config.json. NO uses el ranking\n"
              "     de motivos hasta arreglarlo.", file=sys.stderr)
    elif n_neg:
        print("  ✓  Los motivos de las quejas son estables: el ranking del informe es confiable.")
    if pm < 70:
        print("  ·  (Los motivos POSITIVOS son borrosos, y está bien: 'gracias por el evento'\n"
              "      cae legítimamente en más de una caja. No cambian ninguna decisión.)")


def escribir_auditoria(comentarios, puntuados):
    """La muestra que un humano tiene que leer antes de creerle al número."""
    idxs = list(puntuados)
    random.shuffle(idxs)
    ruta = os.path.join(RAW_DIR, "auditoria_muestra.csv")
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["marca", "comentario", "relevante", "sentimiento", "motivo", "intensidad",
                    "¿coincidís? (sí/no)"])
        for i in idxs[:MUESTRA_VALID]:
            c = comentarios[i]
            w.writerow([c["marca"], c["texto"][:200], c["relevante"], c["sentimiento"],
                        c["motivo"], c["intensidad"], ""])
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

    # Etapa 2 — los motivos se DERIVAN del sector (como los territorios), no salen de una
    # lista fija de seguros. Si la derivación falla, cae a la lista de config.
    categoria = cfg.get("categoria", "la categoría")
    import anthropic
    motivos = _derivar_motivos(anthropic.Anthropic(), categoria, comentarios) \
        or cfg["comentarios"]["motivos"]
    print("\nMotivos de la categoría: %s" % ", ".join(motivos))
    print("\nClasificando con %s…" % args.modelo)
    etiquetas = clasificar(comentarios, motivos, categoria, args.modelo)

    for i, e in etiquetas.items():
        comentarios[i].update({k: e[k] for k in
                               ("relevante", "sentimiento", "motivo", "intensidad")})

    # Motor de sentimiento: RoBERTuito (RoBERTa entrenado con 500M de tweets en español)
    # es el PRIMARIO; Claude queda para el MOTIVO. El sentimiento de Claude se conserva
    # como voto de validación (sent_claude). Si RoBERTuito no está instalado, el
    # sentimiento primario lo pone Claude (fallback), y el pipeline sigue igual.
    # RoBERTuito corre sobre TODOS los comentarios candidatos, no solo sobre los que Claude
    # llegó a etiquetar: es local y gratis, y el sentimiento tiene que salir igual aunque
    # Claude falle (sin crédito, corte de red, rate limit). Claude aporta 'relevante' y
    # 'motivo'; donde no llegó, el comentario queda SIN motivo pero CON sentimiento, que es
    # muchísimo mejor que quedarse sin informe. Antes esto estaba acoplado y una caída de
    # Claude dejaba el análisis de sentimiento en cero.
    import nlp_local
    if nlp_local.disponible():
        idxs = list(range(len(comentarios)))
        preds = nlp_local.sentimiento([comentarios[i]["texto"] for i in idxs])
        for i, p in zip(idxs, preds):
            c = comentarios[i]
            if i in etiquetas:
                c["sent_claude"] = c["sentimiento"]   # queda como voto de validación
            else:
                c["relevante"] = True                 # sin Claude no hay filtro de relevancia
                c["motivo"] = SIN_MOTIVO
                c["intensidad"] = 2
            c["sent_rob"] = p
            c["sentimiento"] = p                      # RoBERTuito manda en el sentimiento
        puntuados = set(idxs)
        print("\nSentimiento: RoBERTuito (primario, %d comentarios) · motivo: Claude (%d)"
              % (len(idxs), len(etiquetas)))
        if len(etiquetas) < len(idxs):
            print("   [aviso] %d comentarios quedaron sin motivo (Claude no respondió). "
                  "El sentimiento SÍ está." % (len(idxs) - len(etiquetas)), file=sys.stderr)
    else:
        puntuados = set(etiquetas)
        print("\n[aviso] RoBERTuito no instalado: el sentimiento primario lo pone Claude. "
              "Para el motor local: pip install pysentimiento", file=sys.stderr)

    salida = os.path.join(RAW_DIR, "comments_scored.jsonl")
    with open(salida, "w", encoding="utf-8") as f:
        for i, c in enumerate(comentarios):
            if i in puntuados:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

    rel = [c for i, c in enumerate(comentarios) if i in puntuados and c["relevante"]]
    sent = collections.Counter(c["sentimiento"] for c in rel)
    n = len(rel) or 1
    print("\nRelevantes (hablan de la marca): %d de %d" % (len(rel), len(puntuados)))
    print("   positivo %3d (%2.0f%%) · neutro %3d (%2.0f%%) · negativo %3d (%2.0f%%)"
          % (sent["positivo"], sent["positivo"] / n * 100,
             sent["neutro"], sent["neutro"] / n * 100,
             sent["negativo"], sent["negativo"] / n * 100))

    # Etapa 3
    escribir_auditoria(comentarios, puntuados)
    if args.validar:
        validar(comentarios, etiquetas, motivos, categoria, args.modelo)

    print("\nSiguiente paso:  python3 analyze.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
