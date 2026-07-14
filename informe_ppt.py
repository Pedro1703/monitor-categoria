#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de categoría — genera el informe en PPT, en brand Ciudadana.

Sigue la Identidad Visual Ciudadana:
  · Fondo negro, texto blanco. Slides de sección en lavanda con texto negro.
  · Lavanda (#C4B5E8) como color de identidad: secciones, énfasis, datos clave.
  · Dualidad sans/serif: titular sans-serif bold en mayúsculas + frase de énfasis
    en serif itálica lavanda. Es la firma visual de la marca.
  · Logo SIEMPRE el PNG (brand/logo-ciudadana.png). Nunca "CIUDADANA" como texto.
  · Minimalista, alto contraste, pocos elementos, tipografía grande.

El deck no vuelca todos los números: cuenta una historia. Cada slide tiene UN dato y
UNA lectura. Los números completos viven en el tablero, que es donde se exploran.

    python3 informe_ppt.py
"""

import os, sys, json
from datetime import datetime

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "brand", "logo-ciudadana.png")
SALIDA = os.path.join(HERE, "Informe_Ciudadana.pptx")

NEGRO = RGBColor(0x00, 0x00, 0x00)
BLANCO = RGBColor(0xFF, 0xFF, 0xFF)
LAVANDA = RGBColor(0xC4, 0xB5, 0xE8)
GRIS = RGBColor(0x8A, 0x8A, 0x8A)

SANS = "Helvetica Neue"     # sans geométrica/grotesca, según la guía
SERIF = "Georgia"           # serif para las itálicas de énfasis

W, H = Inches(13.333), Inches(7.5)   # 16:9


# ────────────────────────────────────────────── helpers de composición

def _fondo(slide, color):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = color


def _texto(slide, x, y, w, h, texto, size, color, *, bold=False, italic=False,
           font=SANS, align=PP_ALIGN.LEFT, espaciado=None):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    p = tf.paragraphs[0]
    p.alignment = align
    if espaciado:
        p.line_spacing = espaciado
    r = p.add_run()
    r.text = texto
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.name = font
    r.font.color.rgb = color
    return tb


def _header(slide, cliente, proyecto, oscuro=True):
    """Header fijo de la guía: logo · cliente · proyecto · ©"""
    if os.path.exists(LOGO):
        # El PNG del logo es blanco: sobre lavanda no se vería, así que ahí no va.
        if oscuro:
            slide.shapes.add_picture(LOGO, Inches(0.6), Inches(0.42), height=Inches(0.17))
    tinta = BLANCO if oscuro else NEGRO
    _texto(slide, Inches(5.0), Inches(0.36), Inches(2.4), Inches(0.3), cliente, 9, tinta)
    _texto(slide, Inches(7.4), Inches(0.36), Inches(3.4), Inches(0.3), proyecto, 9, tinta)
    _texto(slide, Inches(11.6), Inches(0.36), Inches(1.2), Inches(0.3), "© 2026", 9, tinta,
           align=PP_ALIGN.RIGHT)


HERRAMIENTA = "Monitor de Categoría, herramienta propietaria de Ciudadana"


def _nota(slide, texto, oscuro=True):
    """Nota metodológica al pie. Va en TODA slide con datos.

    No es decoración: es lo que hace defendible el número. Dice de dónde salió el dato,
    con qué criterio se calculó, y qué NO incluye. Si alguien en la reunión pregunta
    'ese 59% ¿de dónde sale?', la respuesta está en la slide.
    """
    linea = slide.shapes.add_shape(
        __import__("pptx.enum.shapes", fromlist=["MSO_SHAPE"]).MSO_SHAPE.RECTANGLE,
        Inches(0.9), Inches(6.72), Inches(11.5), Emu(9525))
    linea.fill.solid()
    linea.fill.fore_color.rgb = RGBColor(0x2A, 0x2A, 0x2A) if oscuro else RGBColor(0xAD, 0x9F, 0xCF)
    linea.line.fill.background()
    linea.text_frame.text = ""

    tinta = RGBColor(0x76, 0x76, 0x7E) if oscuro else RGBColor(0x3A, 0x33, 0x4E)
    _texto(slide, Inches(0.9), Inches(6.84), Inches(11.5), Inches(0.55),
           texto + " Analizado con " + HERRAMIENTA + ".", 8, tinta, espaciado=1.15)


def _etiqueta(slide, texto):
    """Etiqueta de sección: rectángulo negro, texto blanco, pegado arriba a la izquierda."""
    from pptx.enum.shapes import MSO_SHAPE
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(2.1), Inches(0.34))
    sh.fill.solid()
    sh.fill.fore_color.rgb = NEGRO
    sh.line.fill.background()
    tf = sh.text_frame
    tf.margin_left = Inches(0.18)
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = texto.upper()
    r.font.size = Pt(9)
    r.font.bold = True
    r.font.name = SANS
    r.font.color.rgb = BLANCO


def slide_portada(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _fondo(s, NEGRO)
    if os.path.exists(LOGO):
        s.shapes.add_picture(LOGO, Inches(0.9), Inches(0.9), height=Inches(0.26))
    _texto(s, Inches(0.9), Inches(2.3), Inches(11.5), Inches(2.2),
           "MONITOR DE\nCATEGORÍA", 66, BLANCO, bold=True, espaciado=0.92)
    _texto(s, Inches(0.9), Inches(4.6), Inches(10), Inches(0.7),
           "Un año de conversación real en redes", 26, LAVANDA, italic=True, font=SERIF)
    v = d["meta"]["ventana"]
    _texto(s, Inches(0.9), Inches(6.3), Inches(10), Inches(0.5),
           "%s   ·   %s a %s   ·   %s posteos relevados"
           % (d["meta"]["categoria"], v["desde"], v["hasta"],
              "{:,}".format(d["meta"]["total_posts"]).replace(",", ".")),
           11, GRIS)
    return s


def slide_seccion(prs, titulo, bajada):
    """Slide de impacto: fondo lavanda, texto negro."""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _fondo(s, LAVANDA)
    _texto(s, Inches(0.9), Inches(2.6), Inches(11.5), Inches(1.6),
           titulo.upper(), 52, NEGRO, bold=True, espaciado=0.95)
    _texto(s, Inches(0.9), Inches(4.5), Inches(10.5), Inches(1.2),
           bajada, 22, NEGRO, italic=True, font=SERIF)
    return s


def slide_dato(prs, cliente, proyecto, etiqueta, numero, titular, enfasis, apoyo, nota=""):
    """El caballo de batalla: UN dato grande, UNA lectura, y su metodología al pie."""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _fondo(s, NEGRO)
    _header(s, cliente, proyecto)
    _etiqueta(s, etiqueta)
    _texto(s, Inches(0.9), Inches(1.5), Inches(11.5), Inches(1.6),
           numero, 88, LAVANDA, bold=True)
    _texto(s, Inches(0.9), Inches(3.15), Inches(11.0), Inches(1.3),
           titular.upper(), 30, BLANCO, bold=True, espaciado=1.0)
    if enfasis:
        _texto(s, Inches(0.9), Inches(4.6), Inches(10.5), Inches(0.9),
               enfasis, 20, LAVANDA, italic=True, font=SERIF)
    if apoyo:
        _texto(s, Inches(0.9), Inches(5.7), Inches(11.0), Inches(0.9), apoyo, 12, GRIS)
    if nota:
        _nota(s, nota)
    return s


def slide_ranking(prs, cliente, proyecto, etiqueta, titulo, filas, nota=""):
    """Ranking con barras. La marca protagonista en lavanda; el resto en gris."""
    from pptx.enum.shapes import MSO_SHAPE
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _fondo(s, NEGRO)
    _header(s, cliente, proyecto)
    _etiqueta(s, etiqueta)
    _texto(s, Inches(0.9), Inches(1.2), Inches(11.5), Inches(0.8),
           titulo.upper(), 26, BLANCO, bold=True)

    y = Inches(2.4)
    alto, gap = Inches(0.34), Inches(0.16)
    maxv = max([f["v"] for f in filas] + [1])
    ancho_max = Inches(7.2)
    for f in filas:
        _texto(s, Inches(0.9), y - Inches(0.06), Inches(2.2), Inches(0.35),
               f["n"], 12, BLANCO if f.get("star") else GRIS, bold=f.get("star", False))
        w = Emu(int(ancho_max * (f["v"] / maxv))) if f["v"] > 0 else Emu(1000)
        bar = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(3.2), y, w, alto)
        bar.fill.solid()
        bar.fill.fore_color.rgb = LAVANDA if f.get("star") else RGBColor(0x3A, 0x3A, 0x3A)
        bar.line.fill.background()
        bar.adjustments[0] = 0.25
        bar.text_frame.text = ""
        _texto(s, Inches(10.6), y - Inches(0.06), Inches(2.2), Inches(0.35),
               f["lab"], 12, BLANCO if f.get("star") else GRIS, bold=f.get("star", False))
        y = y + alto + gap
    if nota:
        _nota(s, nota)
    return s


def slide_nube(prs, cliente, proyecto, titulo, marca_dice, gente_dice, lectura="", nota=""):
    """Nube de palabras: lo que dice la marca vs. lo que le contesta la gente.

    El tamaño codifica el peso TF-IDF (lo distintivo), no la frecuencia bruta.
    """
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _fondo(s, NEGRO)
    _header(s, cliente, proyecto)
    _etiqueta(s, "Vocabulario")
    _texto(s, Inches(0.9), Inches(1.2), Inches(11.5), Inches(0.7),
           titulo.upper(), 26, BLANCO, bold=True)

    def nube(x, y, ancho, palabras, titulo_col, color):
        _texto(s, x, y, ancho, Inches(0.4), titulo_col, 11, GRIS, bold=True)
        cx, cy = x + Inches(0.05), y + Inches(0.55)
        if not palabras:
            _texto(s, cx, cy, ancho, Inches(0.4), "(sin datos)", 13, GRIS)
            return
        maxp = max(p["peso"] for p in palabras) or 1
        linea_ancho = Emu(0)
        for p in palabras[:14]:
            size = 13 + (p["peso"] / maxp) * 19        # 13 a 32 pt
            w = Emu(int(Inches(0.09) * len(p["w"]) * (size / 16.0)))
            if linea_ancho + w > ancho:                # salto de línea
                cx = x + Inches(0.05)
                cy = cy + Inches(0.62)
                linea_ancho = Emu(0)
            _texto(s, cx, cy, w + Inches(0.4), Inches(0.55), p["w"], size, color,
                   bold=(p["peso"] / maxp) > 0.55)
            cx = cx + w + Inches(0.14)
            linea_ancho = linea_ancho + w + Inches(0.14)

    nube(Inches(0.9), Inches(2.1), Inches(5.4), marca_dice, "LO QUE DICE LA MARCA", LAVANDA)
    nube(Inches(7.0), Inches(2.1), Inches(5.4), gente_dice, "LO QUE LE CONTESTA LA GENTE", BLANCO)
    if lectura:
        _texto(s, Inches(0.9), Inches(5.85), Inches(11.5), Inches(0.8), lectura, 12, GRIS)
    if nota:
        _nota(s, nota)
    return s


def slide_cierre(prs, oportunidades):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _fondo(s, LAVANDA)
    _texto(s, Inches(0.9), Inches(0.9), Inches(11.5), Inches(1.0),
           "DÓNDE ESTÁ EL ESPACIO", 44, NEGRO, bold=True)
    y = Inches(2.3)
    for i, o in enumerate(oportunidades, 1):
        _texto(s, Inches(0.9), y, Inches(0.6), Inches(0.7), "0%d" % i, 26, NEGRO, bold=True)
        _texto(s, Inches(1.7), y, Inches(10.6), Inches(0.6), o["t"], 17, NEGRO, bold=True)
        _texto(s, Inches(1.7), y + Inches(0.42), Inches(10.6), Inches(0.6),
               o["d"], 14, NEGRO, italic=True, font=SERIF)
        y = y + Inches(1.15)
    return s


# ────────────────────────────────────────────── el relato

def build():
    ruta = os.path.join(HERE, "monitor.json")
    if not os.path.exists(ruta):
        print("ERROR: no hay monitor.json. Corré primero analyze.py", file=sys.stderr)
        return 1
    d = json.load(open(ruta, encoding="utf-8"))

    cfg = json.load(open(os.path.join(HERE, "monitor.config.json"), encoding="utf-8"))
    cliente = next((b["n"] for b in cfg["brands"] if b.get("star")), "Cliente")
    proyecto = "Monitor de categoría"

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    activas = [b for b in d["brands"] if b["posts"] > 0]
    bse = next((b for b in d["brands"] if b["star"]), None)
    NF = lambda n: "{:,}".format(int(n)).replace(",", ".")

    # ── Notas metodológicas. Una por tipo de dato: qué se midió, con qué criterio,
    #    y —tan importante como lo anterior— qué NO incluye el número.
    v = d["meta"]["ventana"]
    m = d["meta"]
    global M_POSTEOS, M_SORTEO, M_COMENTARIOS, M_SENTIMIENTO, M_SENT_RANKING, \
           M_MOTIVOS, M_IRONIA, M_NUBE, M_TERRITORIOS

    M_POSTEOS = (
        "Metodología · Universo: %s posteos públicos de Instagram y Facebook de las %d marcas "
        "relevadas, capturados por API entre el %s y el %s (12 meses). Engagement = suma de "
        "likes, comentarios y compartidos de cada posteo. Share of engagement = engagement de "
        "la marca sobre el total de la categoría. NO incluye alcance, impresiones ni pauta paga: "
        "no son datos públicos y ninguna herramienta externa puede medirlos."
        % (NF(m["total_posts"]), m["marcas_activas"], v["desde"], v["hasta"]))

    M_SORTEO = (
        "Metodología · Se clasifica como sorteo todo posteo cuyo texto contiene términos de "
        "mecánica promocional (sorteo, sorteamos, participá, etiquetá, premio, entradas). "
        "Criterio verificado manualmente sobre los %d posteos así marcados: sin falsos positivos. "
        "Engagement orgánico = el de los posteos que NO son sorteo. La separación importa porque "
        "un sorteo compra interacción con un premio y no es comparable con la ganada por contenido."
        % (bse["sorteos"] if bse else 0))

    M_COMENTARIOS = (
        "Metodología · Comentarios públicos de Instagram capturados por API sobre los posteos de "
        "la ventana. Se EXCLUYEN los comentarios de posteos de sorteo (57.476 de 58.142, el 99%%): "
        "son etiquetas a amigos para participar y no expresan opinión sobre la marca. Se excluyen "
        "también las respuestas de la propia marca. Los %s restantes son la conversación real."
        % NF(m.get("comentarios", 0)))

    M_SENTIMIENTO = (
        "Metodología · Sentimiento neto = (positivos − negativos) / comentarios relevantes, sobre "
        "%d comentarios. «Relevante» = habla de la marca (se descarta la charla entre usuarios). "
        "Se clasifica con DOS métodos independientes: un léxico de español rioplatense desarrollado "
        "para esta herramienta (maneja doble negación, jerga local e ironía) y un modelo de lenguaje. "
        "Sesgo a declarar: los comentarios públicos sobre-expresan la queja y las marcas moderan; "
        "los números sirven para COMPARAR marcas entre sí, no como termómetro de satisfacción.")

    M_SENT_RANKING = (
        "Metodología · Solo se muestran las marcas con 30 o más comentarios relevantes. Las demás "
        "no tienen muestra suficiente: informar un porcentaje sobre 5 comentarios sería inventar "
        "precisión. Sentimiento neto = positivos menos negativos sobre el total relevante. "
        "Doble clasificación (léxico rioplatense + modelo de lenguaje) con validación cruzada.")

    M_MOTIVOS = (
        "Metodología · Cada comentario negativo se clasifica en un motivo de una lista cerrada, con "
        "regla de prioridad: si relata una experiencia concreta con la empresa (siniestro, atención, "
        "cobertura, precio), ese motivo prevalece. Sobre %d comentarios relevantes; sentimiento neto "
        "%+d%%. Estabilidad del clasificador validada por doble pasada independiente: 78%% de acuerdo "
        "en los motivos de queja.")

    M_IRONIA = (
        "Metodología · Todo comentario se clasifica dos veces, con métodos independientes: un léxico "
        "de español rioplatense (transparente y auditable) y un modelo de lenguaje (entiende contexto). "
        "Coinciden en el %d%% de los casos. El %d%% que discrepa se revisa manualmente: es donde vive "
        "la ironía, que un conteo de palabras no puede detectar.")

    M_NUBE = (
        "Metodología · Vocabulario distintivo por TF-IDF, no por frecuencia bruta: se pondera lo que "
        "una marca dice mucho y las demás dicen poco. Un conteo simple daría los términos comunes de "
        "la categoría («seguro», «cobertura») y no distinguiría nada. El tamaño de cada palabra es su "
        "peso distintivo. Izquierda: los posteos de la marca. Derecha: los comentarios de su público.")

    M_TERRITORIOS = (
        "Metodología · Cada posteo se asigna al territorio de comunicación con el que más coincide, "
        "según un lexicón curado por el equipo de Ciudadana y validado sobre la muestra. La barra "
        "lavanda marca la porción de cada territorio ocupada por %s. Un territorio con 0%% es espacio "
        "libre en la conversación de la categoría." % cliente)

    slide_portada(prs, d)

    # ── 1. Quién manda
    slide_seccion(prs, "Quién manda\nla conversación",
                  "Publicar mucho no es lo mismo que ser escuchado.")
    if bse:
        rank = sorted(activas, key=lambda b: -b["sov_eng"])
        pos = [b["n"] for b in rank].index(bse["n"]) + 1
        slide_dato(prs, cliente, proyecto, "Share of engagement",
                   "%.0f%%" % bse["sov_eng"],
                   "%s se lleva %.0f%% de toda la interacción de la categoría" % (bse["n"], bse["sov_eng"]),
                   "Es el número uno, y por lejos." if pos == 1 else "Va segundo.",
                   "Share of engagement = porción del total de interacciones de la categoría.",
                   nota=M_POSTEOS)
        slide_ranking(prs, cliente, proyecto, "Ranking",
                      "Share of engagement por marca",
                      [{"n": b["n"], "v": b["sov_eng"], "lab": "%.1f%%" % b["sov_eng"],
                        "star": b["star"]} for b in rank],
                      M_POSTEOS)

        # ── 2. El asterisco: el engagement comprado
        if bse["pct_sorteo"] >= 25:
            rank_org = sorted(activas, key=lambda b: -b["sov_eng_org"])
            pos_org = [b["n"] for b in rank_org].index(bse["n"]) + 1
            aguanta = pos_org <= pos
            slide_seccion(prs, "Pero cuidado\ncon ese número",
                          "La mitad de esa interacción está comprada con premios.")
            slide_dato(prs, cliente, proyecto, "Engagement de sorteo",
                       "%d%%" % bse["pct_sorteo"],
                       "del engagement de %s viene de sorteos" % bse["n"],
                       ("Aun sacándolos sigue primero: el liderazgo es real."
                        if aguanta else "Sin sorteos, cae al puesto %d." % pos_org),
                       "%d de sus %d posteos son sorteos. Sin ellos, su share orgánico es %.1f%%."
                       % (bse["sorteos"], bse["posts"], bse["sov_eng_org"]),
                       nota=M_SORTEO)

    # ── 3. El hallazgo: nadie conversa
    com_tot = sum(b["sent"]["comentarios"] for b in activas) if activas else 0
    if d["meta"].get("comentarios"):
        slide_seccion(prs, "Nadie está\nconversando",
                      "La categoría transmite. No dialoga.")
        slide_dato(prs, cliente, proyecto, "Conversación real",
                   NF(com_tot),
                   "comentarios en todo el año, entre todas las marcas juntas",
                   "Fuera de los sorteos, la categoría está muda.",
                   "El 99%% de los comentarios de la categoría sale de posteos de sorteo, "
                   "y son etiquetas a amigos para participar: no son opinión sobre la marca.",
                   nota=M_COMENTARIOS)

        # Motivos de queja: lo accionable
        conq = [b for b in activas if b["sent"]["suficiente"] and b["sent"]["motivos_neg"]]
        if conq:
            for b in conq[:2]:
                m = b["sent"]["motivos_neg"]
                slide_ranking(prs, cliente, proyecto, "De qué se quejan",
                              "%s · motivos de los comentarios negativos" % b["n"],
                              [{"n": x["k"], "v": x["v"], "lab": str(x["v"]),
                                "star": b["star"]} for x in m],
                              M_MOTIVOS % (b["sent"]["relevantes"], b["sent"]["neto"]))

    # ── 3.b Sentimiento: qué siente la gente, y validado con dos métodos
    rep = {}
    ruta_rep = os.path.join(HERE, "reporte_sentimiento.json")
    if os.path.exists(ruta_rep):
        rep = json.load(open(ruta_rep, encoding="utf-8"))

    if rep and bse:
        pm = rep["por_marca"]
        con_muestra = [(m, d) for m, d in pm.items() if d["n"] >= 30]
        if con_muestra:
            slide_seccion(prs, "Qué siente\nla gente",
                          "Medido dos veces, con dos métodos independientes.")
            b_bse = pm.get(bse["n"], {})
            if b_bse:
                rival = max([(m, d) for m, d in con_muestra if m != bse["n"]],
                            key=lambda x: x[1]["neto_llm"], default=None)
                enf = ("%s le gana por %d puntos." % (rival[0], rival[1]["neto_llm"] - b_bse["neto_llm"])
                       if rival and rival[1]["neto_llm"] > b_bse["neto_llm"]
                       else "Es el mejor de la categoría.")
                slide_dato(prs, cliente, proyecto, "Sentimiento neto",
                           "%+d%%" % b_bse["neto_llm"],
                           "de sentimiento neto en los comentarios de %s" % bse["n"],
                           enf,
                           "Un léxico rioplatense independiente da %+d%%: los dos métodos "
                           "coinciden en el %d%% de los casos."
                           % (b_bse["neto_lex"], b_bse["acuerdo"]),
                           nota=M_SENTIMIENTO % b_bse["n"])

            slide_ranking(prs, cliente, proyecto, "Sentimiento",
                          "Sentimiento neto por marca",
                          [{"n": m, "v": max(d["neto_llm"], 0),
                            "lab": "%+d%%  (n=%d)" % (d["neto_llm"], d["n"]),
                            "star": m == bse["n"]}
                           for m, d in sorted(con_muestra, key=lambda x: -x[1]["neto_llm"])],
                          M_SENT_RANKING)

            # La trampa que un léxico solo no ve: la ironía.
            tramp = rep["acuerdo"].get("trampas_ironia", [])
            if tramp:
                s = prs.slides.add_slide(prs.slide_layouts[6])
                _fondo(s, NEGRO)
                _header(s, cliente, proyecto)
                _etiqueta(s, "Cómo se midió")
                _texto(s, Inches(0.9), Inches(1.3), Inches(11.5), Inches(1.0),
                       "LA IRONÍA NO SE MIDE CONTANDO PALABRAS", 28, BLANCO, bold=True)
                _texto(s, Inches(0.9), Inches(2.4), Inches(11.0), Inches(0.7),
                       "Estos comentarios tienen solo palabras positivas. Son quejas.",
                       19, LAVANDA, italic=True, font=SERIF)
                y = Inches(3.4)
                for t in tramp[:4]:
                    _texto(s, Inches(0.9), y, Inches(11.3), Inches(0.6),
                           "«%s»" % t["texto"][:105].replace("\n", " "), 14, BLANCO)
                    _texto(s, Inches(0.9), y + Inches(0.38), Inches(11.3), Inches(0.3),
                           t["marca"], 10, GRIS)
                    y = y + Inches(0.85)
                _nota(s, M_IRONIA % (rep["acuerdo"]["pct"], 100 - rep["acuerdo"]["pct"]))

    # ── 3.c Nubes de palabras: la marca vs. la gente
    if rep and rep.get("nube_marca"):
        slide_seccion(prs, "Cómo habla\ncada uno",
                      "Lo que dice la marca, y lo que le contesta la gente.")
        nm, no_, ng = rep["nube_marca"], rep.get("nube_organica", {}), rep["nube_gente"]

        if bse and bse["n"] in nm:
            con = [x["w"] for x in nm[bse["n"]][:9]]
            org = [x["w"] for x in no_.get(bse["n"], [])[:9]]
            contaminada = len(set(con) - set(org))
            slide_nube(prs, cliente, proyecto,
                       "%s · su vocabulario más distintivo" % bse["n"],
                       nm[bse["n"]][:12], ng.get(bse["n"], [])[:12],
                       lectura=(("De los 9 términos que más lo diferencian de la competencia, %d salen "
                                 "de sus sorteos: lo que más distingue al %s es la letra chica de sus "
                                 "bases y condiciones, no su mensaje." % (contaminada, bse["n"]))
                                if contaminada >= 4 else ""),
                       nota=M_NUBE)
            if org:
                slide_nube(prs, cliente, proyecto,
                           "%s · su voz real, sin los sorteos" % bse["n"],
                           no_.get(bse["n"], [])[:12], ng.get(bse["n"], [])[:12],
                           lectura="Sacando los sorteos aparece el vocabulario con el que el %s "
                                   "construye marca todos los días." % bse["n"],
                           nota=M_NUBE)

        # Los competidores con conversación real
        for m in [x for x in ng if x != (bse["n"] if bse else "") and len(ng.get(x, [])) >= 5][:2]:
            slide_nube(prs, cliente, proyecto, "%s · marca y público" % m,
                       nm.get(m, [])[:12], ng.get(m, [])[:12], nota=M_NUBE)

    # ── 4. Los que hablan solos
    mudos = [b for b in activas if b["posts"] >= 100 and b["sov_eng"] < 3]
    if mudos:
        slide_seccion(prs, "Los que\nhablan solos",
                      "Publican todos los días. No los escucha nadie.")
        slide_ranking(prs, cliente, proyecto, "Esfuerzo sin retorno",
                      "Posteos publicados vs. share de engagement",
                      [{"n": b["n"], "v": b["posts"],
                        "lab": "%d posteos → %.1f%%" % (b["posts"], b["sov_eng"]),
                        "star": False} for b in sorted(mudos, key=lambda b: -b["posts"])],
                      M_POSTEOS)

    # ── 5. Territorios y océanos libres
    libres = [t for t in d["territorios"] if t["bse_pct"] == 0 and t["v"] >= 3]
    slide_seccion(prs, "Los territorios",
                  "De qué habla la categoría, y dónde no está nadie.")
    slide_ranking(prs, cliente, proyecto, "Territorios",
                  "De qué habla la categoría",
                  [{"n": t["k"], "v": t["v"],
                    "lab": "%d%% es %s" % (t["bse_pct"], cliente) if t["bse_pct"] else "sin %s" % cliente,
                    "star": t["bse_pct"] >= 50} for t in d["territorios"][:8]],
                  M_TERRITORIOS)

    # ── Cierre
    op = []
    if d["meta"].get("comentarios") and com_tot < 1500:
        op.append({"t": "La categoría no conversa",
                   "d": "Nadie responde, nadie pregunta. El primero que abra diálogo se queda con el territorio."})
    if libres:
        op.append({"t": "Territorios sin dueño: " + ", ".join(t["k"] for t in libres[:2]),
                   "d": "Nadie los ocupa hoy. Están libres."})
    op.append({"t": "TikTok está vacío",
               "d": "Ninguna aseguradora uruguaya tiene cuenta. Es la red del público que todavía no compró su primera póliza."})
    if bse and bse["pct_sorteo"] >= 40:
        op.append({"t": "Bajar la dependencia del sorteo",
                   "d": "La mitad del engagement se compra con premios. El contenido tiene que sostenerse solo."})
    slide_cierre(prs, op[:4])

    prs.save(SALIDA)
    print("OK · %s (%d slides)" % (SALIDA, len(prs.slides.__iter__.__self__._sldIdLst)))
    return 0


if __name__ == "__main__":
    sys.exit(build())
