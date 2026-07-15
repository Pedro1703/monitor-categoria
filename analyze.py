#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor BSE — análisis: convierte el crudo de Apify en métricas de la ventana relevada.

Qué hace
--------
Lee raw/posts.jsonl + raw/profiles.json y calcula, para BSE y cada competidor (la ventana
la define fetch_apify.py y viaja en el crudo — acá no se asume ningún largo):
volumen y cadencia, engagement total/promedio/tasa, share of voice (por volumen y
por engagement), mezcla de formatos, evolución mes a mes, top posteos con link,
hashtags y territorio de comunicación de cada posteo.

Escribe monitor.json (para servir) y monitor.data.js (para abrir el HTML local
sin servidor, porque fetch() no funciona sobre file://).

Cómo se corre
-------------
    python3 analyze.py             # clasificación por reglas (gratis, instantánea)
    python3 analyze.py --ia        # además clasifica territorios con Claude

La clasificación con IA es opcional y necesita ANTHROPIC_API_KEY. Sin ella, los
territorios salen del lexicón de monitor.config.json — suficiente para el tablero.
"""

import os, re, sys, json, argparse, collections
from datetime import datetime

# Debajo de este N, un porcentaje de sentimiento es humo: no se muestra como número.
MIN_MUESTRA = 30

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "monitor.config.json")
RAW_DIR = os.path.join(HERE, "raw")
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]

# Palabras vacías: se sacan del conteo de términos para que no dominen el ranking.
STOP = set("""
de la el en y a los las un una para con por que del al es se su sus lo como más mas o
the of to and in for on you your we our it is are be this that at from or if but not
te tu tus nos ya muy sin sobre entre cuando donde qué que cómo como también así hay
me mi mis le les ni ese esa esto esta estos estas hasta desde cada todo toda todos todas
""".split())


def mes_label(fecha):
    y, m = int(fecha[:4]), int(fecha[5:7])
    return "%s %s" % (MESES[m - 1], str(y)[2:])


def clasificar_reglas(texto, hashtags, lexicon):
    """Asigna el territorio con más coincidencias de lexicón en el posteo."""
    blob = (texto + " " + " ".join(hashtags)).lower()
    mejor, mejor_score = None, 0
    for territorio, palabras in lexicon.items():
        score = sum(1 for p in palabras if p in blob)
        if score > mejor_score:
            mejor, mejor_score = territorio, score
    return mejor or "Sin clasificar"


def _muestra_estratificada(items, tope):
    """Hasta `tope` items repartidos parejo entre marcas (round-robin).

    Sin esto, la inferencia queda dominada por la marca más prolífica: si una marca
    publica 400 posteos y otra 20, una muestra al azar casi no ve a la chica y los
    territorios/motivos derivados sesgan hacia la grande. Repartir por marca da una base
    más representativa de la categoría, que es lo que se está tratando de caracterizar.
    """
    import random as _r, collections as _c
    porm = _c.defaultdict(list)
    for it in items:
        porm[it.get("marca", "?")].append(it)
    for v in porm.values():
        _r.shuffle(v)
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


def _derivar_territorios(client, categoria, posts):
    """Le pide a Claude los territorios de comunicación propios de la categoría.

    Es lo que hace al informe genérico: en vez de un lexicón fijo (que era de seguros),
    los territorios se deducen del sector real y de una muestra amplia y balanceada de lo
    que las marcas publican. Devuelve una lista de 6-9 nombres cortos, o None si falla.
    """
    # Base ancha: hasta 300 posteos repartidos entre marcas (con Opus y 1M de contexto
    # el techo real es el presupuesto, no el modelo). Cuanto más ve, menos frágil el corte.
    muestra = _muestra_estratificada(posts, 300)
    listado = "\n".join("- [%s] %s" % (p.get("marca", "?"), (p["texto"] or "").replace("\n", " ")[:220])
                        for p in muestra)
    schema = {"type": "object",
              "properties": {"territorios": {"type": "array", "items": {"type": "string"},
                                             "minItems": 5, "maxItems": 9}},
              "required": ["territorios"], "additionalProperties": False}
    try:
        r = client.messages.create(
            model="claude-opus-4-8", max_tokens=1000,
            thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            system=("Sos estratega de comunicación de marca. Dada una categoría y una muestra de "
                    "posteos, definís los TERRITORIOS DE COMUNICACIÓN de esa categoría: los grandes "
                    "temas o ángulos con los que las marcas le hablan a su público (ej. en seguros: "
                    "'Institucional', 'Producto', 'Prevención'; en un banco: 'Beneficios', "
                    "'Educación financiera', 'Patrocinios'). 6 a 9 territorios, nombres cortos, "
                    "mutuamente distintos, en español."),
            messages=[{"role": "user", "content":
                       "Categoría: %s\n\nMuestra de posteos:\n%s" % (categoria, listado)}],
        )
        txt = next(b.text for b in r.content if b.type == "text")
        terr = json.loads(txt)["territorios"]
        return [t.strip() for t in terr if t.strip()][:9] or None
    except Exception as e:
        print("  [aviso] no se pudieron derivar territorios (%s): se usa el lexicón." % e,
              file=sys.stderr)
        return None


def clasificar_ia(posts, lexicon, cfg):
    """
    Capa opcional: reclasifica cada posteo con Claude y le agrega sentimiento.

    Se manda en lotes de captions cortos y se pide salida estructurada, así que una
    corrida de ~1000 posteos son ~25 llamadas. Si falla (sin key, sin red, sin SDK),
    se avisa y se conserva la clasificación por reglas: el monitor nunca se cae por esto.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[aviso] --ia pedido pero falta ANTHROPIC_API_KEY: se usan las reglas.",
              file=sys.stderr)
        return
    try:
        import anthropic
    except ImportError:
        print("[aviso] falta el SDK: pip install anthropic. Se usan las reglas.", file=sys.stderr)
        return

    client = anthropic.Anthropic()
    con_texto = [p for p in posts if (p.get("texto") or "").strip()]

    # Los territorios se DERIVAN del sector, no salen de un lexicón fijo de seguros.
    # Primero se le pide a Claude que proponga los territorios de comunicación propios
    # de esta categoría, mirando una muestra real de posteos. Así el informe se ajusta
    # a bancos, autos, política o lo que sea, sin tocar código.
    territorios = _derivar_territorios(client, cfg["categoria"], con_texto) or list(lexicon)
    globals()["TERRITORIOS_DERIVADOS"] = territorios
    LOTE = 40
    print("Territorios de la categoría: %s" % ", ".join(territorios))
    print("Clasificando %d posteos con Claude…" % len(con_texto))

    schema = {
        "type": "object",
        "properties": {
            "posts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "i": {"type": "integer"},
                        "territorio": {"type": "string", "enum": territorios + ["Sin clasificar"]},
                        "sentimiento": {"type": "string", "enum": ["positivo", "neutro", "negativo"]},
                    },
                    "required": ["i", "territorio", "sentimiento"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["posts"],
        "additionalProperties": False,
    }

    for ini in range(0, len(con_texto), LOTE):
        lote = con_texto[ini:ini + LOTE]
        listado = "\n".join(
            "%d [%s] %s" % (j, p["marca"], (p["texto"] or "").replace("\n", " ")[:400])
            for j, p in enumerate(lote)
        )
        try:
            r = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=4000,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
                system=("Sos analista de comunicación publicitaria. Clasificás posteos de marcas "
                        "de la categoría «%s» en su territorio de comunicación y el sentimiento del "
                        "mensaje de la marca (no el de los comentarios). Devolvés un ítem por posteo, "
                        "con el índice 'i' que te dieron." % cfg["categoria"]),
                messages=[{"role": "user", "content":
                           "Territorios posibles: %s\n\nPosteos:\n%s"
                           % (", ".join(territorios), listado)}],
            )
            texto = next(b.text for b in r.content if b.type == "text")
            for item in json.loads(texto)["posts"]:
                idx = item["i"]
                if 0 <= idx < len(lote):
                    lote[idx]["territorio"] = item["territorio"]
                    lote[idx]["sentimiento"] = item["sentimiento"]
            print("  lote %d-%d ok" % (ini, ini + len(lote)), flush=True)
        except Exception as e:
            print("  [aviso] lote %d falló (%s): quedan las reglas." % (ini, e), file=sys.stderr)


def cargar_comentarios():
    """Comentarios ya clasificados por sentimiento.py. Si no existen, no pasa nada."""
    ruta = os.path.join(RAW_DIR, "comments_scored.jsonl")
    if not os.path.exists(ruta):
        return []
    return [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]


def resumen_sentimiento(comentarios, marca):
    """Sentimiento de una marca, con control honesto de tamaño de muestra.

    Con 8 comentarios, decir '25% negativo' es inventar precisión: dos comentarios
    más y el número se mueve 25 puntos. Debajo de MIN_MUESTRA se devuelve el conteo
    crudo y una bandera, y el tablero muestra 'muestra insuficiente' en vez de un %.
    """
    suyos = [c for c in comentarios if c["marca"] == marca]
    rel = [c for c in suyos if c.get("relevante")]
    n = len(rel)
    s = collections.Counter(c["sentimiento"] for c in rel)
    motivos_neg = collections.Counter(
        c["motivo"] for c in rel
        if c["sentimiento"] == "negativo" and c["motivo"] != "No habla de la marca")
    return {
        "comentarios": len(suyos),
        "relevantes": n,
        "suficiente": n >= MIN_MUESTRA,
        "pos": s["positivo"], "neu": s["neutro"], "neg": s["negativo"],
        "pos_pct": round(s["positivo"] / n * 100) if n else 0,
        "neg_pct": round(s["negativo"] / n * 100) if n else 0,
        # Sentimiento neto: positivos menos negativos, sobre el total relevante.
        "neto": round((s["positivo"] - s["negativo"]) / n * 100) if n else 0,
        "motivos_neg": [{"k": k, "v": v} for k, v in motivos_neg.most_common(5)],
    }


def build(usar_ia):
    cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    ruta_posts = os.path.join(RAW_DIR, "posts.jsonl")
    if not os.path.exists(ruta_posts):
        print("ERROR: no hay raw/posts.jsonl. Corré primero:\n"
              "  export APIFY_TOKEN=apify_api_xxx && python3 fetch_apify.py", file=sys.stderr)
        return 1

    posts = [json.loads(l) for l in open(ruta_posts, encoding="utf-8") if l.strip()]
    perfiles_raw = json.load(open(os.path.join(RAW_DIR, "profiles.json"), encoding="utf-8"))
    perfiles, ventana = perfiles_raw["perfiles"], perfiles_raw["ventana"]

    lexicon = {k: v for k, v in cfg.get("territorios", {}).items() if not k.startswith("_")}
    for p in posts:
        p["eng"] = p["likes"] + p["comments"] + p["shares"]
        p["territorio"] = clasificar_reglas(p["texto"], p["hashtags"], lexicon)
        p["sentimiento"] = "neutro"
    if usar_ia:
        clasificar_ia(posts, lexicon, cfg)

    comentarios = cargar_comentarios()

    semanas = max(ventana["dias"] / 7.0, 1)
    meses_orden = sorted({p["fecha"][:7] for p in posts})
    total_posts = len(posts)
    total_eng = sum(p["eng"] for p in posts) or 1

    marcas = []
    for b in cfg["brands"]:
        nombre = b["n"]
        suyos = [p for p in posts if p["marca"] == nombre]
        eng = sum(p["eng"] for p in suyos)
        seguidores = (perfiles.get(nombre, {}).get("Instagram", {}) or {}).get("seguidores", 0)

        por_mes = collections.Counter(p["fecha"][:7] for p in suyos)
        eng_mes = collections.Counter()
        for p in suyos:
            eng_mes[p["fecha"][:7]] += p["eng"]

        top = sorted(suyos, key=lambda p: -p["eng"])[:5]
        marcas.append({
            "n": nombre,
            "star": b.get("star", False),
            "handles": {k: b.get(k) for k in ("ig", "fb", "x", "tt") if b.get(k)},
            "sin_cuenta": not any(b.get(k) for k in ("ig", "fb", "x", "tt")),
            "seguidores": seguidores,
            "posts": len(suyos),
            "eng": eng,
            "sent": resumen_sentimiento(comentarios, nombre),
            "eng_prom": round(eng / len(suyos)) if suyos else 0,
            # Tasa de engagement: engagement promedio por posteo sobre la base de
            # seguidores. Es la métrica que compara marcas de distinto tamaño.
            "eng_rate": round(eng / len(suyos) / seguidores * 100, 2) if suyos and seguidores else 0,
            "cadencia": round(len(suyos) / semanas, 1),
            "sov_posts": round(len(suyos) / total_posts * 100, 1) if total_posts else 0,
            "sov_eng": round(eng / total_eng * 100, 1),
            "formatos": dict(collections.Counter(p["tipo"] for p in suyos)),
            "redes": dict(collections.Counter(p["red"] for p in suyos)),
            "territorios": dict(collections.Counter(p["territorio"] for p in suyos)),
            "sentimiento": dict(collections.Counter(p["sentimiento"] for p in suyos)),
            "meses": {m: por_mes.get(m, 0) for m in meses_orden},
            "meses_eng": {m: eng_mes.get(m, 0) for m in meses_orden},
            "top_posts": [{"url": p["url"], "fecha": p["fecha"], "red": p["red"],
                           "eng": p["eng"], "likes": p["likes"], "comments": p["comments"],
                           "territorio": p["territorio"],
                           "texto": (p["texto"] or "")[:180]} for p in top],
        })

    activas = [m for m in marcas if m["posts"] > 0]
    bse = next((m for m in marcas if m["star"]), None)

    # Términos y hashtags más usados en la categoría (nube de palabras del tablero)
    palabras = collections.Counter()
    for p in posts:
        for h in p["hashtags"]:
            if len(h) > 2:
                palabras["#" + h] += 2          # los hashtags pesan doble: son intención explícita
        for w in (p["texto"] or "").lower().split():
            w = "".join(c for c in w if c.isalnum() or c in "áéíóúñü")
            if len(w) > 3 and w not in STOP:
                palabras[w] += 1
    top_palabras = [{"w": w, "s": c} for w, c in palabras.most_common(30)]

    # El nombre de la marca protagonista. NUNCA hardcodear una marca: la herramienta es
    # genérica y 'star' puede ser cualquiera. (Este bug — "BSE" fijo — reventaba con
    # cualquier otra categoría.)
    principal = bse["n"] if bse else None

    # Territorios de toda la categoría, con qué marcas los ocupan (mapa de océano)
    terr = collections.Counter(p["territorio"] for p in posts)
    territorios_cat = []
    for t, c in terr.most_common():
        dueños = collections.Counter(p["marca"] for p in posts if p["territorio"] == t)
        territorios_cat.append({
            "k": t, "v": c,
            "pct": round(c / total_posts * 100, 1) if total_posts else 0,
            "marcas": [m for m, _ in dueños.most_common(3)],
            # % del territorio ocupado por la marca protagonista
            "bse_pct": round(dueños.get(principal, 0) / c * 100) if (c and principal) else 0,
        })

    alertas = []
    if bse and bse["posts"]:
        nombres_eng = [m["n"] for m in sorted(activas, key=lambda m: -m["sov_eng"])]
        pos = nombres_eng.index(principal) + 1 if principal in nombres_eng else len(nombres_eng)
        alertas.append({"lvl": "pos" if pos == 1 else "neg",
                        "t": "%s es #%d en share of engagement de la categoría (%.1f%%)."
                             % (principal, pos, bse["sov_eng"])})
        # Conversación de la categoría: si es baja, es una oportunidad.
        com_reales = sum(m["sent"]["comentarios"] for m in activas)
        if comentarios and com_reales:
            alertas.append({"lvl": "neg" if com_reales < 1500 else "pos",
                            "t": "La categoría generó %d comentarios en la ventana entre todas las "
                                 "marcas." % com_reales})
        lider_rate = max(activas, key=lambda m: m["eng_rate"])
        if lider_rate["n"] != principal:
            alertas.append({"lvl": "neg",
                            "t": "%s tiene mejor tasa de engagement que %s (%.2f%% vs %.2f%%): "
                                 "convierte mejor su audiencia."
                                 % (lider_rate["n"], principal, lider_rate["eng_rate"], bse["eng_rate"])})
        # Territorios donde la protagonista está ausente: océano libre o flanco descubierto
        libres = [t["k"] for t in territorios_cat if t["bse_pct"] == 0 and t["v"] >= 3]
        if libres:
            alertas.append({"lvl": "neg",
                            "t": "%s no comunica en: %s." % (principal, ", ".join(libres[:3]))})
        propios = [t["k"] for t in territorios_cat if t["bse_pct"] >= 70]
        if propios:
            alertas.append({"lvl": "pos",
                            "t": "Territorio propio de %s (≥70%% de los posteos): %s."
                                 % (principal, ", ".join(propios[:2]))})

    sin_cuenta = [m["n"] for m in marcas if m["sin_cuenta"]]
    if sin_cuenta:
        alertas.append({"lvl": "pos",
                        "t": "%s no tiene presencia propia en las redes relevadas." % ", ".join(sin_cuenta)})

    data = {
        "meta": {
            "categoria": cfg["categoria"],
            "ventana": ventana,
            "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "total_posts": total_posts,
            "total_eng": total_eng,
            "marcas_activas": len(activas),
            "ia": usar_ia,
            "comentarios": len(comentarios),
            "min_muestra": MIN_MUESTRA,
            "fuente": ("Posteos, engagement, formatos y seguidores: Instagram/Facebook "
                       "vía Apify (datos reales de la ventana). Territorios: %s."
                       % ("clasificación con IA (Claude)" if usar_ia
                          else "clasificación por reglas — correr con --ia para IA")),
            "sesgo_comentarios": ("Los comentarios públicos sobre-expresan la queja (el conforme no "
                                  "comenta) y a la vez las marcas moderan y borran. Los dos sesgos "
                                  "empujan en direcciones opuestas y no se cancelan prolijamente. "
                                  "Estos números sirven para COMPARAR marcas y motivos entre sí, no "
                                  "como termómetro de satisfacción del público."),
        },
        "kpis": [
            {"lab": "Posteos relevados", "num": "{:,}".format(total_posts).replace(",", "."),
             "sub": "%d marcas · %d días" % (len(activas), ventana["dias"])},
            {"lab": "Share of engagement %s" % (principal or ""), "num": "%.1f%%" % (bse["sov_eng"] if bse else 0),
             "sub": "sobre el total de la categoría"},
            {"lab": "Cadencia %s" % (principal or ""), "num": "%.1f" % (bse["cadencia"] if bse else 0),
             "sub": "posteos por semana"},
            {"lab": "Tasa de engagement %s" % (principal or ""), "num": "%.2f%%" % (bse["eng_rate"] if bse else 0),
             "sub": "engagement medio / seguidores"},
        ],
        "meses": [mes_label(m + "-01") for m in meses_orden],
        "meses_key": meses_orden,
        "brands": sorted(marcas, key=lambda m: -m["sov_eng"]),
        "territorios": territorios_cat,
        "keywords": top_palabras,
        "top_categoria": [{"marca": p["marca"], "url": p["url"], "fecha": p["fecha"],
                           "red": p["red"], "eng": p["eng"], "territorio": p["territorio"],
                           "texto": (p["texto"] or "")[:180]}
                          for p in sorted(posts, key=lambda p: -p["eng"])[:10]],
        "alertas": alertas,
    }

    json.dump(data, open(os.path.join(HERE, "monitor.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # El HTML se abre por file:// en las compus del equipo, y ahí fetch() está bloqueado.
    # Este .js con la misma data lo carga con <script src>, que sí funciona sin servidor.
    with open(os.path.join(HERE, "monitor.data.js"), "w", encoding="utf-8") as f:
        f.write("window.MONITOR_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n")

    print("OK · %d posteos · %d marcas activas · ventana %s → %s"
          % (total_posts, len(activas), ventana["desde"], ventana["hasta"]))
    print("Abrí el tablero para ver los resultados.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ia", action="store_true", help="clasificar territorios con Claude")
    sys.exit(build(ap.parse_args().ia))
