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
· Se sacan stopwords del español y el nombre de la propia marca (que aparecería siempre
  primera y no aporta nada).
· Se separan las nubes por sentimiento cuando hay muestra: qué dicen los que elogian y
  qué dicen los que se quejan. Es más accionable que una nube única.

    python3 nubes.py
"""

import os, sys, json, re, math, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "brand", "nubes")

# Mínimo de palabras distintivas para dibujar una nube de sentimiento. Por debajo el
# dibujo queda ralo y engañoso: muestra el tema de un hilo puntual como si fuera la
# conversación de la marca. Mejor no mostrarla: los motivos ya cubren el "por qué".
MIN_PALABRAS = 15

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


def _marcas_a_filtrar():
    """Nombres y handles de todas las marcas de la config, para sacarlos de las nubes."""
    import json as _j
    fuera = set()
    try:
        cfg = _j.load(open(os.path.join(HERE, "monitor.config.json"), encoding="utf-8"))
        for b in cfg["brands"]:
            for parte in re.split(r"[\s/]+", b["n"].lower()):
                fuera.add(parte)
                fuera.add(parte.replace("ó", "o").replace("á", "a").replace("í", "i"))
            for k in ("ig", "fb", "x", "tt"):
                if b.get(k):
                    fuera.add(b[k].lower())
    except Exception:
        pass
    return fuera


def palabras(textos, marca):
    """Frecuencia de palabras con contenido. Saca stopwords, handles y el nombre de la marca."""
    fuera = set(w for w in STOP if not w.startswith("comment_")) | set(RUIDO)
    for p in re.split(r"[\s/]+", marca.lower()):
        fuera.add(p)
        fuera.add(p.replace("ó", "o").replace("á", "a"))
    # Los nombres y handles de TODAS las marcas de la categoría: aparecerían siempre
    # primeros y no aportan. Se leen de la config — nada hardcodeado de una categoría.
    fuera |= _marcas_a_filtrar()
    c = collections.Counter()
    for t in textos:
        # Las @menciones son handles, no opinión: fuera antes de tokenizar.
        limpio = MENCION.sub(" ", (t or "").lower())
        for w in TOKEN.findall(limpio):
            if w not in fuera:
                c[w] += 1
    return c


def palabras_doc(textos, marca):
    """Como palabras(), pero cuenta cada palabra UNA VEZ por comentario.

    Evita la 'burstiness': una persona que repite 'colilla' cuatro veces en un mismo
    comentario, o un hilo entero sobre un posteo puntual, inflaba la palabra como si
    fuera un tema de la marca. Lo que importa es a cuánta gente le salió, no cuántas
    veces la escribió la misma persona.
    """
    c = collections.Counter()
    for t in textos:
        c.update(set(palabras([t], marca)))
    return c


def distintivas(freq_grupo, freq_resto, min_n=2):
    """Palabras PROPIAS de un grupo, no simplemente frecuentes dentro de él.

    Una nube de "de qué se queja la gente" hecha con frecuencia cruda no dice nada: las
    palabras más repetidas en los comentarios negativos son las mismas que en todos los
    demás (el rubro, el país, la marca). Salían 'uruguay', 'seguros', 'seguridad' — que
    no son quejas, son el tema de la categoría.

    Acá cada palabra se pesa por cuánto se CONCENTRA en el grupo respecto del resto de
    los comentarios de esa misma marca:

        peso = f_grupo × log2( p_grupo / p_resto )

    con suavizado de Laplace para que una palabra nueva no divida por cero. Solo quedan
    las de lift > 1 (sobre-representadas) y las que aparecen en al menos `min_n`
    comentarios DISTINTOS: con una o dos menciones sueltas el ruido gana. Así 'uruguay'
    se cae por común y 'colilla' por anecdótica, y queda 'depredador'.
    """
    a = 0.5                                    # suavizado
    n_g = sum(freq_grupo.values()) or 1
    n_r = sum(freq_resto.values()) or 1
    v = len(set(freq_grupo) | set(freq_resto)) or 1
    out = collections.Counter()
    for w, f in freq_grupo.items():
        if f < min_n:
            continue
        p_g = (f + a) / (n_g + a * v)
        p_r = (freq_resto.get(w, 0) + a) / (n_r + a * v)
        lift = p_g / p_r
        if lift > 1:
            out[w] = f * math.log2(lift)
    return out


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

        # Positivos y negativos por separado: es lo accionable. Acá NO va frecuencia cruda
        # sino contraste contra el resto de los comentarios de la misma marca: lo que
        # buscamos es qué distingue a un elogio de una queja, no cuál es el tema del rubro.
        pos = [c["texto"] for c in suyos if c["sentimiento"] == "positivo"]
        neg = [c["texto"] for c in suyos if c["sentimiento"] == "negativo"]
        no_pos = [c["texto"] for c in suyos if c["sentimiento"] != "positivo"]
        no_neg = [c["texto"] for c in suyos if c["sentimiento"] != "negativo"]
        # Se dibujan solo las 30 mejores: más abajo la señal se apaga y la nube vuelve a
        # llenarse de ruido, que es justo lo que este contraste vino a resolver.
        def _nube_sent(textos, resto, archivo, paleta, clave, top_clave):
            if len(textos) < 8:
                return
            f = distintivas(palabras_doc(textos, m), palabras_doc(resto, m))
            # Piso de vocabulario: con menos de MIN_PALABRAS distintivas no hay nube, hay
            # una anécdota. Suele pasar cuando las quejas vienen todas de un mismo hilo:
            # el dibujo queda vacío y, peor, sugiere un tema que no es de la marca.
            if len(f) < MIN_PALABRAS:
                print("      (sin nube de %s: solo %d palabras distintivas, muestra chica)"
                      % (clave, len(f)))
                return
            f = collections.Counter(dict(f.most_common(30)))
            ruta_png = os.path.join(OUT, archivo)
            if render(f, ruta_png, paleta):
                info[clave] = ruta_png
                info[top_clave] = [{"w": w, "n": round(n, 2)} for w, n in f.most_common(8)]

        _nube_sent(pos, no_pos, "%s_pos.png" % base, PALETA_POS, "pos", "top_pos")
        _nube_sent(neg, no_neg, "%s_neg.png" % base, PALETA_NEG, "neg", "top_neg")

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
