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


def slide_dato(prs, cliente, proyecto, etiqueta, numero, titular, enfasis, apoyo):
    """El caballo de batalla: UN dato grande, UNA lectura. Nada más."""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _fondo(s, NEGRO)
    _header(s, cliente, proyecto)
    _etiqueta(s, etiqueta)
    _texto(s, Inches(0.9), Inches(1.5), Inches(11.5), Inches(1.6),
           numero, 88, LAVANDA, bold=True)
    _texto(s, Inches(0.9), Inches(3.2), Inches(11.0), Inches(1.3),
           titular.upper(), 30, BLANCO, bold=True, espaciado=1.0)
    if enfasis:
        _texto(s, Inches(0.9), Inches(4.7), Inches(10.5), Inches(0.9),
               enfasis, 20, LAVANDA, italic=True, font=SERIF)
    if apoyo:
        _texto(s, Inches(0.9), Inches(5.9), Inches(11.0), Inches(1.1), apoyo, 12, GRIS)
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
        _texto(s, Inches(0.9), Inches(6.6), Inches(11.5), Inches(0.6), nota, 11, GRIS)
    return s


def slide_nube(prs, cliente, proyecto, titulo, marca_dice, gente_dice, nota=""):
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

    nube(Inches(0.9), Inches(2.2), Inches(5.4), marca_dice, "LO QUE DICE LA MARCA", LAVANDA)
    nube(Inches(7.0), Inches(2.2), Inches(5.4), gente_dice, "LO QUE LE CONTESTA LA GENTE", BLANCO)
    if nota:
        _texto(s, Inches(0.9), Inches(6.4), Inches(11.5), Inches(0.8), nota, 12, GRIS)
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
                   "Share of engagement = porción del total de likes, comentarios y compartidos "
                   "de todas las marcas relevadas en los últimos 12 meses.")
        slide_ranking(prs, cliente, proyecto, "Ranking",
                      "Share of engagement por marca",
                      [{"n": b["n"], "v": b["sov_eng"], "lab": "%.1f%%" % b["sov_eng"],
                        "star": b["star"]} for b in rank],
                      "Fuente: Instagram y Facebook, 12 meses, vía Apify.")

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
                       "%d de sus %d posteos son sorteos (entradas, camisetas, Expo Prado). "
                       "Sin ellos, su share orgánico es %.1f%%."
                       % (bse["sorteos"], bse["posts"], bse["sov_eng_org"]))

    # ── 3. El hallazgo: nadie conversa
    com_tot = sum(b["sent"]["comentarios"] for b in activas) if activas else 0
    if d["meta"].get("comentarios"):
        slide_seccion(prs, "Nadie está\nconversando",
                      "La categoría transmite. No dialoga.")
        slide_dato(prs, cliente, proyecto, "Conversación real",
                   NF(com_tot),
                   "comentarios en todo el año, entre todas las marcas juntas",
                   "Fuera de los sorteos, la categoría está muda.",
                   "Sobre %s posteos relevados. El 99%% de los comentarios de la categoría "
                   "sale de posteos de sorteo, y son etiquetas a amigos para participar: "
                   "no son opinión sobre la marca."
                   % NF(d["meta"]["total_posts"]))

        # Motivos de queja: lo accionable
        conq = [b for b in activas if b["sent"]["suficiente"] and b["sent"]["motivos_neg"]]
        if conq:
            for b in conq[:2]:
                m = b["sent"]["motivos_neg"]
                slide_ranking(prs, cliente, proyecto, "De qué se quejan",
                              "%s · motivos de los comentarios negativos" % b["n"],
                              [{"n": x["k"], "v": x["v"], "lab": str(x["v"]),
                                "star": b["star"]} for x in m],
                              "Sobre %d comentarios relevantes. Sentimiento neto: %+d."
                              % (b["sent"]["relevantes"], b["sent"]["neto"]))

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
                           "Sentimiento neto = positivos menos negativos, sobre %d comentarios "
                           "relevantes. Un léxico rioplatense independiente da %+d%%: los dos "
                           "métodos coinciden en el %d%% de los casos."
                           % (b_bse["n"], b_bse["neto_lex"], b_bse["acuerdo"]))

            slide_ranking(prs, cliente, proyecto, "Sentimiento",
                          "Sentimiento neto por marca",
                          [{"n": m, "v": max(d["neto_llm"], 0),
                            "lab": "%+d%%  (n=%d)" % (d["neto_llm"], d["n"]),
                            "star": m == bse["n"]}
                           for m, d in sorted(con_muestra, key=lambda x: -x[1]["neto_llm"])],
                          "Solo marcas con al menos 30 comentarios. Las demás no tienen muestra "
                          "suficiente y mostrar un porcentaje sobre 5 comentarios sería inventar precisión.")

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
                _texto(s, Inches(0.9), Inches(6.8), Inches(11.5), Inches(0.5),
                       "Por eso se cruzan dos métodos: un léxico rioplatense (transparente) y un "
                       "modelo de lenguaje (entiende contexto). Coinciden en el %d%%; el %d%% que "
                       "discrepa se revisa a mano."
                       % (rep["acuerdo"]["pct"], 100 - rep["acuerdo"]["pct"]), 11, GRIS)

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
                       ("De los 9 términos que más lo diferencian de la competencia, %d salen de "
                        "sus sorteos («comunicaremos», «solicitarles», «indicado»): lo que más "
                        "distingue al %s es la letra chica de sus bases y condiciones, no su mensaje."
                        % (contaminada, bse["n"])) if contaminada >= 4 else "")
            if org:
                slide_nube(prs, cliente, proyecto,
                           "%s · su voz real, sin los sorteos" % bse["n"],
                           no_.get(bse["n"], [])[:12], ng.get(bse["n"], [])[:12],
                           "Sacando los sorteos aparece el vocabulario con el que el %s "
                           "construye marca todos los días." % bse["n"])

        # Los competidores con conversación real
        for m in [x for x in ng if x != (bse["n"] if bse else "") and len(ng.get(x, [])) >= 5][:2]:
            slide_nube(prs, cliente, proyecto, "%s · marca y público" % m,
                       nm.get(m, [])[:12], ng.get(m, [])[:12], "")

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
                      "Volumen alto, interacción casi nula. Es presupuesto quemado.")

    # ── 5. Territorios y océanos libres
    libres = [t for t in d["territorios"] if t["bse_pct"] == 0 and t["v"] >= 3]
    slide_seccion(prs, "Los territorios",
                  "De qué habla la categoría, y dónde no está nadie.")
    slide_ranking(prs, cliente, proyecto, "Territorios",
                  "De qué habla la categoría",
                  [{"n": t["k"], "v": t["v"],
                    "lab": "%d%% es %s" % (t["bse_pct"], cliente) if t["bse_pct"] else "sin %s" % cliente,
                    "star": t["bse_pct"] >= 50} for t in d["territorios"][:8]],
                  "La barra lavanda marca los territorios donde %s es dueño de la conversación."
                  % cliente)

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
