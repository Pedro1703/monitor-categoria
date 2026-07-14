#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor BSE — capa VIVA: trae 12 meses de actividad en redes con Apify.

Qué hace
--------
Corre los actores de Apify (Instagram, Facebook, TikTok) para todas las marcas de
monitor.config.json, normaliza los posteos a un formato único y los guarda en
raw/posts.jsonl + raw/profiles.json. No calcula métricas: de eso se ocupa analyze.py.

Cómo se corre
-------------
    export APIFY_TOKEN=apify_api_xxx
    python3 fetch_apify.py                 # ventana por defecto (365 días)
    python3 fetch_apify.py --dias 180      # ventana más corta (la mitad del costo)
    python3 fetch_apify.py --redes ig      # solo Instagram

Notas de costo
--------------
El gasto en Apify escala con la cantidad de items scrapeados. `limites.posts_por_marca_por_red`
en la config es el tope duro por marca/red. Referencia: el scraper de Instagram cobra por
cada posteo devuelto, así que bajar la ventana o el tope baja la factura proporcionalmente.

El crudo queda cacheado en raw/. Re-correr analyze.py sobre el crudo no cuesta nada.
Dependencias: solo librería estándar de Python 3.
"""

import os, sys, json, ssl, time, argparse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "monitor.config.json")
RAW_DIR = os.path.join(HERE, "raw")

sys.path.insert(0, HERE)
import config_local
import costos
config_local.cargar()   # lee el .env: las keys se configuran una vez

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
API = "https://api.apify.com/v2"


def _ssl_context():
    """Contexto SSL con los certificados raíz de certifi si están disponibles.

    El Python que se baja de python.org (típico en Mac) no usa el llavero del sistema:
    trae su propio almacén de certificados y lo deja vacío hasta que corrés
    'Install Certificates.command'. Si no, cualquier HTTPS revienta con
    CERTIFICATE_VERIFY_FAILED. Apuntar explícitamente a certifi evita depender de eso.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()


# ---------------------------------------------------------------- Apify

def _req(url, data=None, method=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def chequear_conexion():
    """Valida SSL + token contra Apify antes de gastar un peso.

    Falla temprano y con un mensaje accionable, en vez de escupir un stack trace
    a mitad de camino o —peor— arrancar actores que después no pueden leer nada.
    Ojo: HTTPError hereda de URLError, así que va primero.
    """
    try:
        r = _req("%s/users/me?token=%s" % (API, APIFY_TOKEN))
        u = r.get("data", {})
        plan = (u.get("plan") or {}).get("id") or "free"
        print("Apify OK · usuario: %s · plan: %s" % (u.get("username", "?"), plan))
        return True
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print("ERROR: Apify rechazó el token (HTTP %s). Revisá APIFY_TOKEN." % e.code,
                  file=sys.stderr)
        else:
            print("ERROR: Apify respondió HTTP %s." % e.code, file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            print("ERROR: Python no puede verificar certificados HTTPS.\n"
                  "  Es el clásico de Python bajado de python.org en Mac. Arreglalo con:\n"
                  "      python3 -m pip install --upgrade certifi\n"
                  "  (o corriendo 'Install Certificates.command' en tu carpeta de Python).",
                  file=sys.stderr)
        else:
            print("ERROR: no hay conexión con Apify (%s)." % e.reason, file=sys.stderr)
        return False


def run_actor(actor, payload, etiqueta, timeout_min=20):
    """Arranca el actor, espera a que termine y devuelve los items del dataset.

    Se usa el modo asíncrono (arrancar + pollear) en vez de run-sync porque run-sync
    corta a los 300 s y una corrida de 12 meses sobre 9 marcas los excede sin problema.
    """
    print("  → Apify: %s (%s)" % (actor, etiqueta), flush=True)
    try:
        run = _req("%s/acts/%s/runs?token=%s" % (API, actor, APIFY_TOKEN), payload)["data"]
    except urllib.error.HTTPError as e:
        print("  [error] no se pudo arrancar %s: HTTP %s %s"
              % (actor, e.code, e.read().decode("utf-8", "replace")[:300]), file=sys.stderr)
        return []

    run_id, ds_id = run["id"], run["defaultDatasetId"]
    limite = time.time() + timeout_min * 60
    estado = run["status"]
    while estado in ("READY", "RUNNING") and time.time() < limite:
        time.sleep(10)
        try:
            run = _req("%s/actor-runs/%s?token=%s" % (API, run_id, APIFY_TOKEN))["data"]
            estado = run["status"]
        except Exception as e:
            print("  [aviso] fallo al pollear la corrida: %s" % e, file=sys.stderr)
            break

    if estado != "SUCCEEDED":
        print("  [aviso] corrida terminó en estado %s — se usa lo que haya en el dataset."
              % estado, file=sys.stderr)

    items, offset = [], 0
    while True:
        try:
            page = _req("%s/datasets/%s/items?token=%s&offset=%d&limit=1000"
                        % (API, ds_id, APIFY_TOKEN, offset))
        except Exception as e:
            print("  [error] no se pudieron leer los items: %s" % e, file=sys.stderr)
            break
        if not page:
            break
        items.extend(page)
        offset += len(page)
        if len(page) < 1000:
            break
    print("    %d items" % len(items), flush=True)
    return items


# ---------------------------------------------------------------- normalizadores
# Cada actor devuelve un esquema distinto. Acá se aplanan todos al mismo registro:
#   {marca, red, id, url, fecha, texto, hashtags, likes, comments, shares, views, tipo}

def _num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _fecha(v):
    """Devuelve 'YYYY-MM-DD' desde ISO string o epoch."""
    if not v:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%d")
    s = str(v)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.replace("+00:00", "Z") if fmt.endswith("Z") else s,
                                     fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s[:10] if len(s) >= 10 else None


def norm_ig(it, por_handle):
    h = (it.get("ownerUsername") or "").lower()
    marca = por_handle.get(h)
    if not marca:
        return None
    tipo = {"Video": "video", "Sidecar": "carrusel", "Image": "imagen"}.get(it.get("type"), "imagen")
    return {
        "marca": marca, "red": "Instagram", "id": it.get("shortCode") or it.get("id"),
        "url": it.get("url") or ("https://www.instagram.com/p/%s/" % it.get("shortCode")),
        "fecha": _fecha(it.get("timestamp")),
        "texto": it.get("caption") or "",
        "hashtags": [str(x).lower().lstrip("#") for x in (it.get("hashtags") or [])],
        "likes": _num(it.get("likesCount")), "comments": _num(it.get("commentsCount")),
        "shares": 0,
        "views": _num(it.get("videoPlayCount") or it.get("videoViewCount")),
        "tipo": tipo,
    }


def norm_fb(it, por_handle):
    # El actor de Facebook cambia nombres de campo según la versión: se prueban varios.
    url = it.get("url") or it.get("postUrl") or ""
    marca = None
    for h, m in por_handle.items():
        if h in url.lower() or h in str(it.get("pageName", "")).lower() \
           or h in str(it.get("facebookUrl", "")).lower():
            marca = m
            break
    if not marca:
        return None
    reacciones = it.get("likes")
    if reacciones is None:
        reacciones = (it.get("reactions") or {}).get("likes") if isinstance(it.get("reactions"), dict) \
            else it.get("reactionsCount")
    return {
        "marca": marca, "red": "Facebook", "id": it.get("postId") or it.get("id"),
        "url": url,
        "fecha": _fecha(it.get("time") or it.get("timestamp") or it.get("date")),
        "texto": it.get("text") or it.get("message") or "",
        "hashtags": [],
        "likes": _num(reacciones), "comments": _num(it.get("comments")),
        "shares": _num(it.get("shares")), "views": _num(it.get("viewsCount")),
        "tipo": "video" if it.get("media") and "video" in str(it.get("media")).lower() else "imagen",
    }


def norm_tt(it, por_handle):
    h = ((it.get("authorMeta") or {}).get("name") or "").lower()
    marca = por_handle.get(h)
    if not marca:
        return None
    return {
        "marca": marca, "red": "TikTok", "id": it.get("id"),
        "url": it.get("webVideoUrl") or "",
        "fecha": _fecha(it.get("createTimeISO") or it.get("createTime")),
        "texto": it.get("text") or "",
        "hashtags": [str((x or {}).get("name", "")).lower() for x in (it.get("hashtags") or [])],
        "likes": _num(it.get("diggCount")), "comments": _num(it.get("commentCount")),
        "shares": _num(it.get("shareCount")), "views": _num(it.get("playCount")),
        "tipo": "video",
    }


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=None, help="ventana en días (default: config)")
    ap.add_argument("--redes", default="ig,fb,tt", help="redes a traer: ig,fb,tt")
    args = ap.parse_args()

    if not APIFY_TOKEN:
        print("ERROR: falta APIFY_TOKEN.\n"
              "  export APIFY_TOKEN=apify_api_xxx && python3 fetch_apify.py", file=sys.stderr)
        return 1
    if not chequear_conexion():
        return 1

    cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    dias = args.dias or cfg.get("ventana_dias", 365)
    redes = [r.strip() for r in args.redes.split(",") if r.strip()]
    tope = cfg["limites"]["posts_por_marca_por_red"]
    actors = cfg["actors"]

    desde_dt = datetime.now(timezone.utc) - timedelta(days=dias)
    desde = desde_dt.strftime("%Y-%m-%d")
    print("Monitor BSE · ventana: %s → hoy (%d días)\n" % (desde, dias))

    os.makedirs(RAW_DIR, exist_ok=True)
    posts, perfiles = [], {}

    # ---- Instagram: posteos + perfil (seguidores)
    if "ig" in redes:
        ig_map = {b["ig"].lower(): b["n"] for b in cfg["brands"] if b.get("ig")}
        if ig_map:
            urls = ["https://www.instagram.com/%s/" % h for h in ig_map]
            items = run_actor(actors["instagram_posts"], {
                "directUrls": urls,
                "resultsType": "posts",
                "resultsLimit": tope,
                "onlyPostsNewerThan": desde,
                "addParentData": False,
            }, "posteos IG · %d marcas" % len(ig_map))
            posts += [p for p in (norm_ig(i, ig_map) for i in items) if p]
            costos.registrar("ig_post", len(items),
                             len(items) / 1000 * costos.PRECIOS["ig_post"]["usd_1000"],
                             "%d marcas · %d días" % (len(ig_map), dias))

            perf = run_actor(actors["instagram_profile"], {"usernames": list(ig_map)},
                             "perfiles IG (seguidores)")
            for it in perf:
                u = (it.get("username") or "").lower()
                if u in ig_map:
                    perfiles.setdefault(ig_map[u], {})["Instagram"] = {
                        "seguidores": _num(it.get("followersCount")),
                        "posts_total": _num(it.get("postsCount")),
                        "url": "https://www.instagram.com/%s/" % u,
                    }

    # ---- Facebook
    if "fb" in redes:
        fb_map = {b["fb"].lower(): b["n"] for b in cfg["brands"] if b.get("fb")}
        if fb_map:
            items = run_actor(actors["facebook_posts"], {
                "startUrls": [{"url": "https://www.facebook.com/%s" % h} for h in fb_map],
                "resultsLimit": tope,
                "onlyPostsNewerThan": desde,
            }, "posteos FB · %d marcas" % len(fb_map))
            posts += [p for p in (norm_fb(i, fb_map) for i in items) if p]
            costos.registrar("fb_post", len(items),
                             len(items) / 1000 * costos.PRECIOS["fb_post"]["usd_1000"],
                             "%d marcas · %d días" % (len(fb_map), dias))

    # ---- TikTok
    if "tt" in redes:
        tt_map = {b["tt"].lower(): b["n"] for b in cfg["brands"] if b.get("tt")}
        if tt_map:
            items = run_actor(actors["tiktok_posts"], {
                "profiles": list(tt_map),
                "resultsPerPage": tope,
                "oldestPostDateUnified": desde,
            }, "posteos TikTok · %d marcas" % len(tt_map))
            posts += [p for p in (norm_tt(i, tt_map) for i in items) if p]

    # Filtro de ventana: algunos actores ignoran o aproximan onlyPostsNewerThan.
    antes = len(posts)
    posts = [p for p in posts if p.get("fecha") and p["fecha"] >= desde]
    if antes != len(posts):
        print("\n(%d posteos descartados por caer fuera de la ventana)" % (antes - len(posts)))

    with open(os.path.join(RAW_DIR, "posts.jsonl"), "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    json.dump({"perfiles": perfiles,
               "ventana": {"desde": desde, "hasta": datetime.now().strftime("%Y-%m-%d"), "dias": dias},
               "capturado": datetime.now().isoformat(timespec="seconds")},
              open(os.path.join(RAW_DIR, "profiles.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    por_marca = {}
    for p in posts:
        por_marca[p["marca"]] = por_marca.get(p["marca"], 0) + 1
    print("\nOK · %d posteos guardados en raw/posts.jsonl" % len(posts))
    for m, c in sorted(por_marca.items(), key=lambda x: -x[1]):
        print("   %-18s %d" % (m, c))
    sin_datos = [b["n"] for b in cfg["brands"] if b["n"] not in por_marca]
    if sin_datos:
        print("\n   sin posteos en la ventana: %s" % ", ".join(sin_datos))
    print("\nSiguiente paso:  python3 analyze.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
