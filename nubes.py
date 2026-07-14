#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nubes de palabras — de los COMENTARIOS de cada marca. Qué dice la gente, y cuánto lo repite.

CÓMO SE HACEN
=============
Nube de frecuencia, como corresponde: el tamaño de cada palabra es proporcional a cuántas
veces la gente la escribió. Se renderiza con la librería `wordcloud`, que hace el layout
con un algoritmo de empaquetado real — sin superposiciones, sin palabras cortadas.

Se generan como IMAGEN (PNG) y se embeben en el PPT. Es lo que hacen los informes de
Volvo, y es la razón por la que no se rompen: el layout lo resuelve el renderer, no
posiciones calculadas a mano que se pisan cuando cambia el texto.

CRITERIOS
=========
· Solo comentarios del público (se excluyen las respuestas de la propia marca).
· Se excluyen los comentarios de posteos de sorteo: son "@fulano vamos!!" y taparían
  todo con menciones y con la palabra "sorteo".
· Se sacan stopwords del español y el nombre de la propia marca (que aparecería siempre
  primera y no aporta nada).
· Se separan las nubes por sentimiento cuando hay muestra: qué dicen los que elogian y
  qué dicen los que se quejan. Es más accionable que una nube única.

    python3 nubes.py
"""

import os, sys, json, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "brand", "nubes")

# Colores CiudadanIA / Ciudadana: la nube se tiñe con la paleta, no con arcoíris.
PALETA_LAV = ["#C4B5E8", "#A897D6", "#8F7BC4", "#E0D7F2", "#B3A2DF"]
PALETA_POS = ["#7BE0A8", "#5CCF92", "#A8EDC6", "#3FB97A"]
PALETA_NEG = ["#FF8A7A", "#E86B5C", "#FFB0A4", "#D14E3E"]

# Stopwords. Una nube "científica" no es la que dibuja lindo: es la que solo deja
# palabras con CONTENIDO. Los verbos vacíos ("hace", "dando", "quieren") y los deícticos
# ("ahora", "después", "todavía") son los que más se repiten en cualquier corpus y no
# dicen nada — si no se filtran, tapan la señal y la nube no significa nada.
STOP = set("""
a al algo algún alguna algunas alguno algunos ante antes aquel aquella aquellos aqui aquí
asi así aun aún bien cada como cómo con contra cual cuál cuando cuándo de del desde donde
dónde dos el él ella ellas ellos en entre era eran eres es esa ese eso esos esta está
estaba estamos estan están estar estas este esto estos estoy fue fui gran ha había han
hasta hay he hizo hoy la las le les lo los más mas me mi mis mucho muy nada ni no nos
nosotros o os otra otro para pero poco por porque que qué quien quién se ser si sí sin
sobre solo son soy su sus también tan tanto te tener tengo ti tiene tienen toda todas
todo todos tu tus un una uno unos usted ustedes va vamos van vos y ya yo les q d
the of to and in for on is are be it we our this that at from or if but not you your

comment_deicticos
ahora antes después despues luego todavia todavía siempre nunca jamás jamas aún aun ya
entonces mientras además ademas incluso encima tampoco recién recien

comment_verbos_vacios
hace hacen hacer haciendo hizo hacé hecho haber habia había hay hubo tener tiene tienen
tengo teniendo dar dando dado doy dio dejen dejar deja dejo poner pone puso pongan
quiere quieren quiero querer queria quería puede pueden podría podria puedan pudo poder
usar usan usa vale valen ver viendo vieron veo mira miren mirar saber sabe sepan
decir dice dicen dijo digan estar estan están estuvo sigue siguen seguir vamo vamos
acaban acabar llevan lleva llevar viene vienen venir sale salen salir queda quedan

comment_cuantificadores
cosa cosas algo alguien nadie todo todos toda todas otros otras otro otra mismo misma
gente persona personas muchas muchos poco pocos varios varias cada
grande grandes mejor mejores peor peores bueno buena buenos buenas malo mala
años año meses mes dias días día semana semanas veces vez tiempo
""".split())

# Ruido de red social.
RUIDO = set("""
jaja jajaja jajajaja jajaj jeje jejeje https http www com instagram
hola buenas buenos chau saludos
""".split())

TOKEN = re.compile(r"[a-záéíóúñü]{4,}", re.I)
MENCION = re.compile(r"@[\w.]+")


def palabras(textos, marca):
    """Frecuencia de palabras con contenido. Saca stopwords, handles y el nombre de la marca."""
    fuera = set(w for w in STOP if not w.startswith("comment_")) | set(RUIDO)
    for p in re.split(r"[\s/]+", marca.lower()):
        fuera.add(p)
        fuera.add(p.replace("ó", "o").replace("á", "a"))
    # El nombre de la marca y sus handles aparecerían siempre primeros y no aportan.
    fuera |= {"seguro", "seguros", "bse", "porto", "mapfre", "sura", "surco",
              "metlife", "cristobal", "cristóbal", "bseuruguay", "portoseguro",
              "segurossurauy", "metlifeuruguay", "sancristobaluy", "surcoseguros"}
    c = collections.Counter()
    for t in textos:
        # Las @menciones son handles, no opinión: fuera antes de tokenizar.
        limpio = MENCION.sub(" ", (t or "").lower())
        for w in TOKEN.findall(limpio):
            if w not in fuera:
                c[w] += 1
    return c


def render(freqs, destino, paleta, ancho=1800, alto=900):
    """Dibuja la nube. El tamaño = frecuencia. Layout empaquetado, sin solapes."""
    from wordcloud import WordCloud
    import random

    if not freqs or sum(freqs.values()) < 3:
        return None

    def color(*a, **k):
        return random.choice(paleta)

    wc = WordCloud(
        width=ancho, height=alto,
        background_color=None, mode="RGBA",      # fondo transparente: va sobre el negro
        max_words=60,
        prefer_horizontal=0.92,                  # casi todo horizontal: se lee mejor
        relative_scaling=0.55,                   # el tamaño sigue de cerca a la frecuencia
        min_font_size=14, max_font_size=130,
        margin=6,                                # aire entre palabras: nada se toca
        color_func=color,
        font_path=_fuente(),
        random_state=7,                          # reproducible: misma nube siempre
        collocations=False,                      # no inventa bigramas
    ).generate_from_frequencies(freqs)

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    wc.to_file(destino)
    return destino


def _fuente():
    for f in ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/Library/Fonts/Arial.ttf"):
        if os.path.exists(f):
            return f
    return None


def build():
    ruta = os.path.join(RAW, "comments_scored.jsonl")
    if not os.path.exists(ruta):
        print("ERROR: faltan comentarios clasificados (corré sentimiento.py)", file=sys.stderr)
        return {}
    coments = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]

    os.makedirs(OUT, exist_ok=True)
    salida = {}
    marcas = sorted({c["marca"] for c in coments})

    for m in marcas:
        suyos = [c for c in coments if c["marca"] == m and c.get("relevante")]
        if len(suyos) < 10:
            continue
        base = m.lower().replace(" ", "_").replace("ó", "o")
        info = {"n": len(suyos)}

        freq = palabras([c["texto"] for c in suyos], m)
        p = render(freq, os.path.join(OUT, "%s.png" % base), PALETA_LAV)
        if p:
            info["todas"] = p
            info["top"] = [{"w": w, "n": n} for w, n in freq.most_common(12)]

        # Positivos y negativos por separado: es lo accionable.
        pos = [c["texto"] for c in suyos if c["sentimiento"] == "positivo"]
        neg = [c["texto"] for c in suyos if c["sentimiento"] == "negativo"]
        if len(pos) >= 8:
            fp = palabras(pos, m)
            if render(fp, os.path.join(OUT, "%s_pos.png" % base), PALETA_POS):
                info["pos"] = os.path.join(OUT, "%s_pos.png" % base)
                info["top_pos"] = [{"w": w, "n": n} for w, n in fp.most_common(8)]
        if len(neg) >= 8:
            fn = palabras(neg, m)
            if render(fn, os.path.join(OUT, "%s_neg.png" % base), PALETA_NEG):
                info["neg"] = os.path.join(OUT, "%s_neg.png" % base)
                info["top_neg"] = [{"w": w, "n": n} for w, n in fn.most_common(8)]

        salida[m] = info
        print("  %-16s %3d comentarios · %s" % (m, len(suyos),
              " + ".join(k for k in ("todas", "pos", "neg") if k in info)))

    json.dump(salida, open(os.path.join(HERE, "nubes.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return salida


if __name__ == "__main__":
    print("Nubes de palabras — de los comentarios de la gente:\n")
    build()
    print("\nPNG en brand/nubes/")
