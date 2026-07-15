#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de categoría — baja los comentarios de los posteos ya capturados.

Qué hace
--------
Lee raw/posts.jsonl, elige de qué posteos vale la pena bajar comentarios y los trae
con Apify. Escribe raw/comments.jsonl.

Decisiones que importan
-----------------------
1. NO guarda el nombre de usuario de quien comenta. Los comentaristas son personas
   reales, no marcas, y este repo es público. Se guarda el texto y las métricas; la
   identidad se descarta apenas se usa para marcar si el comentario es de la propia
   marca respondiendo (esos se excluyen del análisis).

2. TODAS las redes capturadas, no solo Instagram. Se bajan comentarios de Instagram y
   Facebook (uno por posteo) y respuestas de X/Twitter (búsqueda 'to:handle'). Cada
   comentario queda etiquetado con su red, así el análisis puede segmentar por red.
   Antes esto era solo Instagram y el análisis de sentimiento se quedaba corto: los
   comentarios de FB y X no entraban. Ya no.

3. El costo escala con la cantidad de COMENTARIOS, no de posteos. Por eso se filtra
   antes: posteos con pocos comentarios no aportan señal y cuestan igual. El techo
   'max_comentarios_total' se reparte entre Instagram y Facebook; X tiene su propio tope
   chico (es barato y su volumen es marginal).

Cómo se corre
-------------
    export APIFY_TOKEN=apify_api_xxx
    python3 fetch_comments.py --estimar    # NO gasta: dice cuántos hay y cuánto sale
    python3 fetch_comments.py              # los baja
    python3 fetch_comments.py --top 30     # solo los 30 posteos más comentados por marca
"""

import os, re, sys, json, argparse, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(HERE, "raw")
CONFIG_PATH = os.path.join(HERE, "monitor.config.json")

sys.path.insert(0, HERE)
from fetch_apify import run_actor, chequear_conexion, _num, _fecha, APIFY_TOKEN  # noqa: E402
import costos  # noqa: E402

# Precio por resultado en Apify (plan Starter). Solo se usa para estimar antes de gastar.
USD_POR_1000 = 2.30


def cargar_posts():
    ruta = os.path.join(RAW_DIR, "posts.jsonl")
    if not os.path.exists(ruta):
        print("ERROR: no hay raw/posts.jsonl. Corré primero fetch_apify.py", file=sys.stderr)
        sys.exit(1)
    return [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]


def elegir(posts, cfg, top, muestra=1.0):
    """Elige de qué posteos bajar comentarios. El costo se controla con dos topes
    genéricos: 'por_posteo' (máx. comentarios por posteo, así un posteo viral no se come
    todo el presupuesto) y 'max_comentarios_total' (techo de la corrida). No hay nada
    específico de una categoría."""
    conf = cfg["comentarios"]
    minimo = conf["min_comentarios"]

    # Instagram y Facebook se bajan por posteo (un comentario cuelga de un posteo). X va
    # por otra vía (búsqueda de respuestas al handle), así que se maneja aparte en main.
    cands = [p for p in posts if p["red"] in ("Instagram", "Facebook") and p["comments"] >= minimo]

    if top:
        por_marca = collections.defaultdict(list)
        for p in sorted(cands, key=lambda p: -p["comments"]):
            if len(por_marca[p["marca"]]) < top:
                por_marca[p["marca"]].append(p)
        cands = [p for lista in por_marca.values() for p in lista]

    # TECHO DURO: si la suma proyectada de comentarios pasa el máximo, se recortan los
    # posteos (empezando por los MENOS comentados, que aportan menos señal por dólar)
    # hasta entrar. Sin esto, una categoría viral baja decenas de miles y gasta cualquier cosa.
    tope_post = conf["por_posteo"]
    max_total = conf.get("max_comentarios_total", 999999)
    cands.sort(key=lambda p: -p["comments"])
    acum, recortados = 0, []
    for p in cands:
        n = min(p["comments"], tope_post)
        if acum + n > max_total:
            continue
        acum += n
        recortados.append(p)
    if len(recortados) < len(cands):
        print("  (techo de %d comentarios: se relevan %d posteos de %d; el resto queda fuera)"
              % (max_total, len(recortados), len(cands)))

    # MUESTREO ALEATORIO: si el usuario pidió una fracción, se baraja al azar y se toman
    # posteos hasta llegar a esa fracción del total de comentarios. Es aleatorio de verdad
    # (semilla del reloj), y reduce el costo proporcionalmente porque baja MENOS comentarios.
    if muestra < 0.999 and recortados:
        import random as _r
        _r.seed()                            # semilla del reloj: cada corrida es distinta
        objetivo = sum(min(p["comments"], tope_post) for p in recortados) * muestra
        _r.shuffle(recortados)
        elegidos_m, acum = [], 0
        for p in recortados:
            if acum >= objetivo:
                break
            elegidos_m.append(p)
            acum += min(p["comments"], tope_post)
        print("  (muestra aleatoria %d%%: %d posteos de %d, ~%d comentarios)"
              % (round(muestra * 100), len(elegidos_m), len(recortados), acum))
        return elegidos_m
    return recortados


def _handles(cfg, red_key):
    return {b[red_key].lower(): b["n"] for b in cfg["brands"] if b.get(red_key)}


def _bajar_ig(elegidos, cfg, tope, handles):
    """Comentarios de Instagram: uno por posteo, vía el actor con resultsType=comments."""
    por_url = {p["url"]: p for p in elegidos}
    items = run_actor(cfg["actors"]["instagram_posts"], {
        "directUrls": [p["url"] for p in elegidos],
        "resultsType": "comments",
        "resultsLimit": tope,
    }, "comentarios IG · %d posteos" % len(elegidos), timeout_min=40)
    out, de_la_marca = [], 0
    for it in items:
        url = it.get("postUrl") or it.get("url") or ""
        post = por_url.get(url)
        if not post:
            sc = (it.get("postUrl") or "").rstrip("/").split("/")[-1]
            post = next((p for p in elegidos if p["id"] == sc), None)
        if not post:
            continue
        if (it.get("ownerUsername") or "").lower() in handles:
            de_la_marca += 1                 # la marca respondiendo: no es opinión del público
            continue
        texto = (it.get("text") or "").strip()
        if not texto:
            continue
        out.append({"marca": post["marca"], "red": "Instagram",
                    "post_url": post["url"], "post_fecha": post["fecha"],
                    "fecha": _fecha(it.get("timestamp")), "texto": texto,
                    "likes": _num(it.get("likesCount"))})
    return out, de_la_marca, len(items)


def _bajar_fb(elegidos, cfg, tope, desde):
    """Comentarios de Facebook: uno por posteo, vía apify~facebook-comments-scraper."""
    por_url = {p["url"]: p for p in elegidos}
    items = run_actor(cfg["actors"]["facebook_comments"], {
        "startUrls": [{"url": p["url"]} for p in elegidos],
        "resultsLimit": tope,
        "onlyCommentsNewerThan": desde,
        "includeNestedComments": True,
    }, "comentarios FB · %d posteos" % len(elegidos), timeout_min=40)
    out = []
    for it in items:
        url = it.get("facebookUrl") or it.get("postUrl") or it.get("url") or ""
        post = por_url.get(url) or next((p for p in elegidos if p["url"] and p["url"] in url), None)
        if not post:
            continue
        texto = (it.get("text") or it.get("message") or "").strip()
        if not texto:
            continue
        out.append({"marca": post["marca"], "red": "Facebook",
                    "post_url": post["url"], "post_fecha": post["fecha"],
                    "fecha": _fecha(it.get("date") or it.get("timestamp")),
                    "texto": texto, "likes": _num(it.get("likesCount"))})
    return out, len(items)


def _bajar_x(cfg, posts, tope_marca, desde):
    """Respuestas de X/Twitter. El actor de tweets no baja hilos por posteo, así que se
    buscan tweets 'to:handle' — la conversación pública dirigida a la marca. Se excluye a
    la marca respondiéndose a sí misma."""
    handles = _handles(cfg, "x")
    if not handles:
        return [], 0
    con_x = {p["marca"] for p in posts if p["red"] == "X" and p["comments"] > 0}
    objetivo = [h for h, m in handles.items() if m in con_x] or list(handles)
    out, n_items = [], 0
    for h in objetivo:
        items = run_actor(cfg["actors"]["x_posts"], {
            "searchTerms": ["to:%s" % h],
            "maxItems": tope_marca,
            "start": desde,
            "sort": "Latest",
        }, "respuestas X · @%s" % h, timeout_min=20)
        n_items += len(items)
        for it in items:
            a = it.get("author") or {}
            if (a.get("userName") or a.get("username") or "").lower() == h:
                continue                     # la marca respondiéndose a sí misma
            texto = (it.get("text") or it.get("fullText") or "").strip()
            if not texto:
                continue
            out.append({"marca": handles[h], "red": "X",
                        "post_url": "", "post_fecha": "",
                        "fecha": _fecha(it.get("createdAt")), "texto": texto,
                        "likes": _num(it.get("likeCount"))})
    return out, n_items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estimar", action="store_true", help="solo estima volumen y costo; no gasta")
    ap.add_argument("--top", type=int, default=None,
                    help="solo los N posteos más comentados de cada marca")
    ap.add_argument("--muestra", type=float, default=1.0,
                    help="fracción (0-1) de comentarios a bajar, muestra ALEATORIA (default 1.0 = todo)")
    args = ap.parse_args()

    from datetime import datetime, timedelta
    cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    conf = cfg["comentarios"]
    posts = cargar_posts()
    tope = conf["por_posteo"]
    dias = cfg.get("ventana_dias", 365)
    desde = (datetime.utcnow() - timedelta(days=dias)).strftime("%Y-%m-%d")

    # IG + FB comparten el techo 'max_comentarios_total' y el muestreo (van por posteo).
    elegidos = elegir(posts, cfg, args.top, args.muestra)
    ig_sel = [p for p in elegidos if p["red"] == "Instagram"]
    fb_sel = [p for p in elegidos if p["red"] == "Facebook"]

    # X tiene un tope propio y chico (por handle): el actor busca respuestas 'to:handle',
    # es barato ($0,40/1000) y su volumen es marginal, no debe comerse el presupuesto.
    x_map = _handles(cfg, "x")
    x_posts = [p for p in posts if p["red"] == "X"]
    x_tope_marca = tope
    esp_x = min(sum(min(p["comments"], tope) for p in x_posts),
                x_tope_marca * len(x_map)) if x_map else 0

    esp_ig = sum(min(p["comments"], tope) for p in ig_sel)
    esp_fb = sum(min(p["comments"], tope) for p in fb_sel)
    P = costos.PRECIOS
    costo = (esp_ig / 1000 * P["ig_comment"]["usd_1000"]
             + esp_fb / 1000 * P["fb_comment"]["usd_1000"]
             + esp_x / 1000 * P["x_comment"]["usd_1000"])

    print("Comentarios a bajar, por red (tope %d/posteo):" % tope)
    print("   Instagram : %5d  (%d posteos)" % (esp_ig, len(ig_sel)))
    print("   Facebook  : %5d  (%d posteos)" % (esp_fb, len(fb_sel)))
    print("   X/Twitter : %5d  (búsqueda to:@handle, %d marcas)" % (esp_x, len(x_map)))
    print("Costo estimado en Apify         : USD %.2f" % costo)
    print()
    por_marca = collections.Counter()
    for p in ig_sel + fb_sel:
        por_marca[p["marca"]] += min(p["comments"], tope)
    for m, c in por_marca.most_common():
        print("   %-18s %5d comentarios (IG+FB)" % (m, c))

    if args.estimar:
        print("\n(--estimar: no se gastó nada. Sacá el flag para bajarlos.)")
        return 0
    if not (ig_sel or fb_sel or x_map):
        print("\nNo hay posteos que cumplan el filtro. Nada que bajar.")
        return 0
    if not APIFY_TOKEN or not chequear_conexion():
        return 1

    ig_handles = _handles(cfg, "ig")
    comentarios, de_la_marca = [], 0
    n_ig = n_fb = n_x = 0

    print("\nBajando comentarios…")
    if ig_sel:
        c_ig, dm, n_ig = _bajar_ig(ig_sel, cfg, tope, ig_handles)
        comentarios += c_ig
        de_la_marca += dm
    if fb_sel:
        c_fb, n_fb = _bajar_fb(fb_sel, cfg, tope, desde)
        comentarios += c_fb
    if x_map:
        c_x, n_x = _bajar_x(cfg, posts, x_tope_marca, desde)
        comentarios += c_x

    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(RAW_DIR, "comments.jsonl"), "w", encoding="utf-8") as f:
        for c in comentarios:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # El gasto se registra por red, con el precio real de cada actor.
    if n_ig:
        costos.registrar("ig_comment", n_ig, n_ig / 1000 * P["ig_comment"]["usd_1000"],
                         "%d posteos IG" % len(ig_sel))
    if n_fb:
        costos.registrar("fb_comment", n_fb, n_fb / 1000 * P["fb_comment"]["usd_1000"],
                         "%d posteos FB" % len(fb_sel))
    if n_x:
        costos.registrar("x_comment", n_x, n_x / 1000 * P["x_comment"]["usd_1000"],
                         "%d marcas X" % len(x_map))

    print("\nOK · %d comentarios guardados (%d eran respuestas de la marca, descartados)"
          % (len(comentarios), de_la_marca))
    cnt = collections.Counter((c["marca"], c["red"]) for c in comentarios)
    por_red = collections.Counter(c["red"] for c in comentarios)
    print("Por red: " + " · ".join("%s %d" % (r, n) for r, n in por_red.most_common()))
    for (m, r), c in cnt.most_common():
        print("   %-18s %-10s %5d" % (m, r, c))
    print("\nSiguiente paso:  python3 sentimiento.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
