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

2. Solo Instagram. Facebook necesita otro actor y su volumen de comentarios en esta
   categoría es marginal. Si algún día hace falta, se agrega acá.

3. El costo escala con la cantidad de COMENTARIOS, no de posteos. Por eso se filtra
   antes: posteos con pocos comentarios no aportan señal y cuestan igual.

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


def es_sorteo(post, patron):
    """¿Es un posteo de sorteo?

    Importa muchísimo. En seguros Uruguay, ~25 posteos de sorteo concentran el 97% de
    TODOS los comentarios de la categoría, y esos comentarios son '@juan @pedro vamos!!':
    valor reputacional cero. Bajarlos costaría US$130 para analizar spam.

    Se excluyen ACÁ, antes de pagarlos. Filtrarlos después (en sentimiento.py) sería
    plata ya gastada. La opinión real de la gente vive en la cola larga: los posteos
    con 5, 20 o 50 comentarios.
    """
    return bool(patron.search((post.get("texto") or "")))


def elegir(posts, cfg, top):
    """Elige de qué posteos bajar comentarios. Acá se decide el 90% del costo."""
    conf = cfg["comentarios"]
    patron = re.compile(conf["patron_sorteo"], re.I)
    minimo = conf["min_comentarios"]

    cands = [p for p in posts if p["red"] == "Instagram" and p["comments"] >= minimo]
    sorteos = []
    if conf.get("excluir_sorteos", True):
        sorteos = [p for p in cands if es_sorteo(p, patron)]
        cands = [p for p in cands if not es_sorteo(p, patron)]

    if top:
        por_marca = collections.defaultdict(list)
        for p in sorted(cands, key=lambda p: -p["comments"]):
            if len(por_marca[p["marca"]]) < top:
                por_marca[p["marca"]].append(p)
        cands = [p for lista in por_marca.values() for p in lista]
    return cands, sorteos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estimar", action="store_true", help="solo estima volumen y costo; no gasta")
    ap.add_argument("--top", type=int, default=None,
                    help="solo los N posteos más comentados de cada marca")
    args = ap.parse_args()

    cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    conf = cfg["comentarios"]
    posts = cargar_posts()
    elegidos, sorteos = elegir(posts, cfg, args.top)

    # commentsCount de cada posteo ya vino en la captura: el volumen no se adivina, se suma.
    tope = conf["por_posteo"]
    esperados = sum(min(p["comments"], tope) for p in elegidos)
    costo = esperados / 1000 * USD_POR_1000

    ig = [p for p in posts if p["red"] == "Instagram"]
    total_existentes = sum(p["comments"] for p in ig)
    en_sorteos = sum(p["comments"] for p in sorteos)
    print("Posteos de Instagram capturados : %d" % len(ig))
    print("Comentarios que existen en total: %d" % total_existentes)
    if sorteos:
        print("  ├─ en %d posteos de SORTEO   : %d  (%.0f%% del total) → EXCLUIDOS"
              % (len(sorteos), en_sorteos, en_sorteos / max(total_existentes, 1) * 100))
        print("  │   (son '@fulano vamos!!' — no son opinión; bajarlos costaría USD %.0f)"
              % (en_sorteos / 1000 * USD_POR_1000))
        print("  └─ conversación real         : %d" % (total_existentes - en_sorteos))
    print("Posteos elegidos (>=%d comentarios%s): %d"
          % (conf["min_comentarios"], ", top %d por marca" % args.top if args.top else "", len(elegidos)))
    print("Comentarios a bajar (tope %d/posteo): %d" % (tope, esperados))
    print("Costo estimado en Apify         : USD %.2f" % costo)
    print()
    por_marca = collections.Counter()
    for p in elegidos:
        por_marca[p["marca"]] += min(p["comments"], tope)
    for m, c in por_marca.most_common():
        print("   %-18s %5d comentarios" % (m, c))

    if args.estimar:
        print("\n(--estimar: no se gastó nada. Sacá el flag para bajarlos.)")
        return 0
    if not elegidos:
        print("\nNo hay posteos que cumplan el filtro. Nada que bajar.")
        return 0
    if not APIFY_TOKEN or not chequear_conexion():
        return 1

    # Handles de las marcas: sirven para detectar (y descartar) a la marca respondiendo.
    handles = {b["ig"].lower(): b["n"] for b in cfg["brands"] if b.get("ig")}
    por_url = {p["url"]: p for p in elegidos}

    print("\nBajando comentarios…")
    items = run_actor(cfg["actors"]["instagram_posts"], {
        "directUrls": [p["url"] for p in elegidos],
        "resultsType": "comments",
        "resultsLimit": tope,
    }, "comentarios · %d posteos" % len(elegidos), timeout_min=40)

    comentarios, de_la_marca = [], 0
    for it in items:
        url = it.get("postUrl") or it.get("url") or ""
        post = por_url.get(url)
        if not post:
            # El actor devuelve la URL del posteo con variantes; se busca por shortcode.
            sc = (it.get("postUrl") or "").rstrip("/").split("/")[-1]
            post = next((p for p in elegidos if p["id"] == sc), None)
        if not post:
            continue

        autor = (it.get("ownerUsername") or "").lower()
        if autor in handles:
            de_la_marca += 1          # la marca respondiendo: no es opinión del público
            continue

        texto = (it.get("text") or "").strip()
        if not texto:
            continue
        comentarios.append({
            "marca": post["marca"],
            "post_url": post["url"],
            "post_fecha": post["fecha"],
            "fecha": _fecha(it.get("timestamp")),
            "texto": texto,
            "likes": _num(it.get("likesCount")),
            # El username se usa acá arriba y se descarta: no se persiste. Ver el docstring.
        })

    os.makedirs(RAW_DIR, exist_ok=True)
    with open(os.path.join(RAW_DIR, "comments.jsonl"), "w", encoding="utf-8") as f:
        for c in comentarios:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    costos.registrar("ig_comment", len(items),
                     len(items) / 1000 * costos.PRECIOS["ig_comment"]["usd_1000"],
                     "%d posteos" % len(elegidos))
    real = len(comentarios) + de_la_marca
    print("\nOK · %d comentarios guardados (%d eran respuestas de la marca, descartados)"
          % (len(comentarios), de_la_marca))
    print("Costo real aproximado: USD %.2f" % (real / 1000 * USD_POR_1000))
    cnt = collections.Counter(c["marca"] for c in comentarios)
    for m, c in cnt.most_common():
        print("   %-18s %5d" % (m, c))
    print("\nSiguiente paso:  python3 sentimiento.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
