#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reporte profundo de sentimiento: lexicón rioplatense × Claude, y nube de palabras por marca.

QUÉ HACE, Y POR QUÉ ASÍ
=======================
Corre DOS analizadores independientes sobre los mismos comentarios:
  · lexico_uy  — lexicón rioplatense, transparente, gratis, reproducible
  · Claude     — entiende contexto e ironía, pero es una caja negra

Y los CRUZA. Ese cruce es el aporte real:

  · Donde AMBOS coinciden  → el dato es sólido. Podés presentarlo.
  · Donde DISCREPAN        → casi siempre hay ironía, sarcasmo o una frase ambigua.
                             Se listan aparte para que los lea un humano, en vez de
                             promediarlos a ciegas y ensuciar el número.

Un solo método no te dice dónde desconfiar. Dos, sí. El desacuerdo es la señal.

NUBE DE PALABRAS — por qué no es un conteo de frecuencia
========================================================
Contar palabras da basura: "seguro", "BSE" y "gracias" ganan en todas las marcas y no
distinguen nada. Se usa TF-IDF: pondera lo que una marca dice MUCHO y las demás dicen
POCO. El resultado son los términos DISTINTIVOS de cada marca — su voz propia, no el
vocabulario compartido de la categoría.

Se hacen dos nubes por marca:
  · lo que dice LA MARCA   (sus posteos)      → cómo se posiciona
  · lo que dice LA GENTE   (sus comentarios)  → cómo la reciben
La brecha entre ambas es, muchas veces, el hallazgo.

    python3 reporte_sentimiento.py
"""

import os, sys, json, math, csv, collections, re

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "raw")
sys.path.insert(0, HERE)

from lexico_uy import analizar  # noqa: E402

STOP = set("""
de la el en y a los las un una para con por que del al es se su sus lo como más mas o
te tu tus nos ya muy sin sobre entre cuando donde qué que cómo también así hay this
me mi mis le les ni ese esa esto esta estos estas hasta desde cada todo toda todos todas
al ser son fue era han ha he has hemos está están estoy estamos si no sí lo la le
you your the of to and in for on is are be it we our this that at from or if but not
seguro seguros bse porque pero muy más ver más solo sólo tan
""".split())

TOKEN = re.compile(r"[a-záéíóúñü]{4,}", re.I)


def tokens(texto):
    return [w for w in TOKEN.findall((texto or "").lower()) if w not in STOP]


def tfidf(docs_por_marca, top=18):
    """Términos DISTINTIVOS de cada marca. TF-IDF, no frecuencia cruda.

    Sin IDF, todas las marcas comparten las mismas palabras ('seguro', 'cobertura') y
    la nube no dice nada. El IDF castiga lo que dicen todos y premia lo propio.
    """
    tf, df = {}, collections.Counter()
    for marca, textos in docs_por_marca.items():
        c = collections.Counter()
        for t in textos:
            c.update(tokens(t))
        tf[marca] = c
        for w in set(c):
            df[w] += 1

    N = len(docs_por_marca) or 1
    out = {}
    for marca, c in tf.items():
        total = sum(c.values()) or 1
        puntajes = []
        for w, n in c.items():
            if n < 2:                      # una sola aparición es ruido
                continue
            idf = math.log((N + 1) / (df[w] + 0.5))
            puntajes.append((w, (n / total) * idf, n))
        puntajes.sort(key=lambda x: -x[1])
        out[marca] = [{"w": w, "peso": round(s, 5), "n": n} for w, s, _ in
                      [(w, s, n) for w, s, n in puntajes[:top]]]
    return out


def main():
    ruta = os.path.join(RAW_DIR, "comments_scored.jsonl")
    if not os.path.exists(ruta):
        print("ERROR: faltan comentarios clasificados. Corré sentimiento.py", file=sys.stderr)
        return 1
    coments = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]
    posts = [json.loads(l) for l in open(os.path.join(RAW_DIR, "posts.jsonl"),
                                          encoding="utf-8") if l.strip()]

    # ── 1. Lexicón sobre cada comentario
    for c in coments:
        r = analizar(c["texto"])
        c["lex_sent"] = r.sentimiento
        c["lex_score"] = r.score
        c["lex_evidencia"] = [(t, p, n) for t, p, n in r.evidencia]
        c["lex_ironia"] = r.ironia

    rel = [c for c in coments if c.get("relevante")]

    # ── 2. El cruce: dónde coinciden y dónde no
    ac = sum(1 for c in rel if c["lex_sent"] == c["sentimiento"])
    n = len(rel) or 1
    matriz = collections.Counter((c["sentimiento"], c["lex_sent"]) for c in rel)
    discrepan = [c for c in rel if c["lex_sent"] != c["sentimiento"]]

    print("═" * 74)
    print("  ACUERDO ENTRE LOS DOS MÉTODOS INDEPENDIENTES")
    print("═" * 74)
    print("  Comentarios relevantes analizados: %d" % n)
    print("  Coinciden Claude y el lexicón     : %d  (%.0f%%)" % (ac, ac / n * 100))
    print("  Discrepan                         : %d  (%.0f%%)  ← acá vive la ironía"
          % (len(discrepan), len(discrepan) / n * 100))
    print("\n  Matriz (filas = Claude, columnas = lexicón):")
    et = ["positivo", "neutro", "negativo"]
    print("      %-12s %8s %8s %8s" % ("", "pos", "neu", "neg"))
    for a in et:
        print("      %-12s %8d %8d %8d"
              % (a, matriz[(a, "positivo")], matriz[(a, "neutro")], matriz[(a, "negativo")]))

    # El caso más peligroso: el lexicón lo lee positivo y Claude lo lee negativo.
    # Son las ironías: "excelente, solo 3 meses para pagarme".
    trampas = [c for c in rel if c["sentimiento"] == "negativo" and c["lex_sent"] == "positivo"]
    if trampas:
        print("\n  ⚠ %d comentarios que un lexicón solo habría contado como POSITIVOS," % len(trampas))
        print("    y en realidad son quejas. Es exactamente lo que el LLM aporta:\n")
        for c in trampas[:5]:
            print("      · [%s] %s" % (c["marca"], c["texto"][:78].replace("\n", " ")))

    # ── 2b. Tercer voto OPCIONAL: RoBERTuito local (gratis, si está instalado)
    # No cambia ningún número del informe: solo agrega una medida de acuerdo con un
    # segundo modelo ENTRENADO. Si pysentimiento no está, esto no corre y listo.
    import nlp_local
    validacion = {"metodos": 2, "claude_vs_lexico": round(ac / n * 100), "robertuito": False}
    if nlp_local.disponible():
        print("\n" + "═" * 74)
        print("  TERCER VOTO — RoBERTuito local (modelo entrenado con 500M de tweets)")
        print("═" * 74)
        preds = nlp_local.sentimiento([c["texto"] for c in rel])
        if preds:
            for c, p in zip(rel, preds):
                c["rob_sent"] = p
            ac_rob = sum(1 for c in rel if c.get("rob_sent") == c["sentimiento"])
            ac_rob_lex = sum(1 for c in rel if c.get("rob_sent") == c["lex_sent"])
            tres = sum(1 for c in rel
                       if c.get("rob_sent") == c["sentimiento"] == c["lex_sent"])
            validacion = {"metodos": 3, "claude_vs_lexico": round(ac / n * 100),
                          "robertuito": True,
                          "robertuito_vs_claude": round(ac_rob / n * 100),
                          "robertuito_vs_lexico": round(ac_rob_lex / n * 100),
                          "los_tres": round(tres / n * 100)}
            print("  Coinciden RoBERTuito y Claude : %d  (%.0f%%)" % (ac_rob, ac_rob / n * 100))
            print("  Coinciden RoBERTuito y lexicón: %d  (%.0f%%)" % (ac_rob_lex, ac_rob_lex / n * 100))
            print("  Los TRES coinciden            : %d  (%.0f%%)  ← el núcleo más confiable"
                  % (tres, tres / n * 100))
    else:
        print("\n  (RoBERTuito local no instalado — se omite el tercer voto. "
              "Para activarlo: pip install pysentimiento)")

    # ── 3. Sentimiento por marca, con los dos métodos lado a lado
    print("\n" + "═" * 74)
    print("  SENTIMIENTO POR MARCA — los dos métodos, uno al lado del otro")
    print("═" * 74)
    print("  %-15s %6s %10s %10s %9s" % ("MARCA", "N", "NETO Claude", "NETO léxico", "ACUERDO"))
    por_marca = collections.defaultdict(list)
    for c in rel:
        por_marca[c["marca"]].append(c)
    reporte_marcas = {}
    for m, cs in sorted(por_marca.items(), key=lambda x: -len(x[1])):
        nn = len(cs)
        neto_llm = sum(1 for c in cs if c["sentimiento"] == "positivo") - \
                   sum(1 for c in cs if c["sentimiento"] == "negativo")
        neto_lex = sum(1 for c in cs if c["lex_sent"] == "positivo") - \
                   sum(1 for c in cs if c["lex_sent"] == "negativo")
        acu = sum(1 for c in cs if c["lex_sent"] == c["sentimiento"]) / nn * 100
        flag = "" if nn >= 30 else "  (muestra chica)"
        print("  %-15s %6d %9d%% %9d%% %8.0f%%%s"
              % (m, nn, neto_llm / nn * 100, neto_lex / nn * 100, acu, flag))
        reporte_marcas[m] = {"n": nn, "neto_llm": round(neto_llm / nn * 100),
                             "neto_lex": round(neto_lex / nn * 100), "acuerdo": round(acu)}

    # ── 4. Nubes de palabras por marca (TF-IDF): la marca vs. la gente
    #
    # Dos vocabularios distintivos por marca: lo que la marca dice en sus posteos
    # y lo que la gente le responde en los comentarios. La brecha entre ambos —de
    # qué habla la marca vs. de qué habla su audiencia— es el hallazgo.
    marcas = sorted({p["marca"] for p in posts})
    nube_marca = tfidf({m: [p["texto"] for p in posts if p["marca"] == m] for m in marcas})
    nube_gente = tfidf({m: [c["texto"] for c in coments if c["marca"] == m]
                        for m in marcas if any(c["marca"] == m for c in coments)})

    print("\n" + "═" * 74)
    print("  VOCABULARIO DISTINTIVO POR MARCA  (TF-IDF: lo propio, no lo compartido)")
    print("═" * 74)
    for m in marcas:
        pm = nube_marca.get(m, [])
        pg = nube_gente.get(m, [])
        if not pm and not pg:
            continue
        print("\n  ── %s" % m)
        if pm:
            print("     LO QUE LA MARCA DICE : %s" % ", ".join(x["w"] for x in pm[:9]))
        if pg:
            print("     LA GENTE le responde : %s" % ", ".join(x["w"] for x in pg[:9]))

    # ── 5. Salidas
    salida = {
        "acuerdo": {"n": n, "coinciden": ac, "pct": round(ac / n * 100),
                    "discrepan": len(discrepan),
                    "trampas_ironia": [{"marca": c["marca"], "texto": c["texto"][:200]}
                                       for c in trampas[:15]]},
        "por_marca": reporte_marcas,
        "nube_marca": nube_marca,
        "nube_gente": nube_gente,
        "validacion": validacion,
    }
    json.dump(salida, open(os.path.join(HERE, "reporte_sentimiento.json"), "w",
                           encoding="utf-8"), ensure_ascii=False, indent=1)

    # CSV con TODO: cada comentario, los dos scores, y la evidencia del lexicón.
    # Es el archivo que se abre en Excel para auditar de verdad.
    with open(os.path.join(RAW_DIR, "sentimiento_detalle.csv"), "w",
              encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["marca", "comentario", "Claude", "motivo (Claude)", "léxico",
                    "score léxico", "¿coinciden?", "por qué lo dice el léxico", "post"])
        for c in sorted(coments, key=lambda c: (c["marca"], c.get("sentimiento", ""))):
            if not c.get("relevante"):
                continue
            ev = " | ".join("%s(%.2f,%s)" % (t, p, n) for t, p, n in c["lex_evidencia"][:6])
            w.writerow([c["marca"], c["texto"][:300], c["sentimiento"], c["motivo"],
                        c["lex_sent"], c["lex_score"],
                        "sí" if c["lex_sent"] == c["sentimiento"] else "NO",
                        ev, c["post_url"]])

    print("\n" + "═" * 74)
    print("  reporte_sentimiento.json         → los datos, para el tablero")
    print("  raw/sentimiento_detalle.csv      → cada comentario con los dos scores")
    print("                                     y POR QUÉ el léxico dijo lo que dijo")
    print("═" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
