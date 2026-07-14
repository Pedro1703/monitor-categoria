#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de categoría — app local.

Levanta un servidor en tu máquina y abre el navegador. Ahí elegís las cuentas a
trackear, las redes, el período y si querés comentarios; te estima el costo de API
ANTES de gastar; confirmás; corre; y te deja el tablero y el PPT en brand Ciudadana.

    python3 app.py          (o doble clic en Abrir_Monitor.command)

Todo corre local: los datos de la categoría nunca salen de tu máquina. Las keys se
leen del .env (ver configurar.py) y no viajan a ningún lado salvo a Apify/Anthropic.

Servidor de la librería estándar a propósito: sin Flask, sin dependencias, sin build.
"""

import os, sys, json, re, threading, webbrowser, subprocess, collections
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config_local  # noqa: E402
import costos  # noqa: E402

CONFIG_PATH = os.path.join(HERE, "monitor.config.json")
RAW_DIR = os.path.join(HERE, "raw")
PUERTO = 8765

# Los precios ya no viven acá: costos.py los tiene verificados contra la facturación
# real, y si hay corridas previas usa el promedio medido en vez de una constante.

# Estado de la corrida en curso (lo lee el front por polling).
ESTADO = {"corriendo": False, "paso": "", "log": [], "fin": None, "error": None}


def log(msg):
    ESTADO["log"].append(msg)
    print(msg, flush=True)


# ────────────────────────────────────────────────── estimación

def estimar(cuentas, redes, dias, con_comentarios, con_ia=True):
    """Estima volumen y costo. NO gasta nada.

    Principio: distinguir siempre lo MEDIDO de lo SUPUESTO, y decirlo. El usuario
    decide si vale la pena gastar, y para eso necesita saber cuánto confiar en el número.

      · Los precios unitarios están VERIFICADOS contra la facturación real de Apify.
      · El VOLUMEN es lo incierto. Si ya se corrió antes, se usa la cadencia real de
        cada marca (deja de ser supuesto). Si no, un supuesto declarado, con una banda
        de ±45% — que es la incertidumbre real medida contra la primera corrida.
      · Los comentarios, si hay una captura previa, son un conteo EXACTO: sabemos
        cuántos hay porque cada posteo trajo su commentsCount.
    """
    semanas = dias / 7.0
    hist = _historico()
    lineas = []

    filas, tot_ig, tot_fb = [], 0, 0
    for c in cuentas:
        cad = hist.get(c["n"], {}).get("cadencia")
        supuesto = cad is None
        cad = cad if cad is not None else costos.CADENCIA_DEFECTO
        p_ig = int(cad * semanas) if (c.get("ig") and "ig" in redes) else 0
        p_fb = int(cad * semanas * costos.CADENCIA_FB_FACTOR) if (c.get("fb") and "fb" in redes) else 0
        tot_ig += p_ig
        tot_fb += p_fb
        filas.append({"marca": c["n"], "posts_ig": p_ig, "posts_fb": p_fb, "supuesto": supuesto})

    pr_ig, f_ig = costos.precio("ig_post")
    pr_fb, f_fb = costos.precio("fb_post")
    costo = 0.0
    if tot_ig:
        c_ig = tot_ig / 1000 * pr_ig
        costo += c_ig
        lineas.append({"k": "Posteos de Instagram", "n": tot_ig, "usd": round(c_ig, 2),
                       "precio": "US$ %.2f /1.000" % pr_ig, "fuente": f_ig})
    if tot_fb:
        c_fb = tot_fb / 1000 * pr_fb
        costo += c_fb
        lineas.append({"k": "Posteos de Facebook", "n": tot_fb, "usd": round(c_fb, 2),
                       "precio": "US$ %.2f /1.000" % pr_fb, "fuente": f_fb})

    com = {"n": 0, "exacto": False, "sorteos_excluidos": 0, "usd_sorteos": 0}
    if con_comentarios:
        # OJO: el conteo exacto solo vale para las marcas que REALMENTE se capturaron.
        # Si el usuario pide una marca nueva, no se le puede dar el conteo de otra.
        marcas_ig = [c["n"] for c in cuentas if c.get("ig") and "ig" in redes]
        reales = _comentarios_reales(marcas_ig)
        if reales is not None:
            com["n"], com["sorteos_excluidos"] = reales
            com["exacto"] = True     # no es estimación: es el conteo real de ESTAS marcas
        else:
            # Sin captura previa de estas marcas: la categoría conversa poquísimo
            # (0,8 comentarios por posteo, fuera de sorteos). El supuesto más frágil.
            com["n"] = int(tot_ig * 0.8)

        pr_c, f_c = costos.precio("ig_comment")
        c_com = com["n"] / 1000 * pr_c
        costo += c_com
        lineas.append({"k": "Comentarios (sin sorteos)", "n": com["n"], "usd": round(c_com, 2),
                       "precio": "US$ %.2f /1.000" % pr_c,
                       "fuente": "conteo EXACTO de la captura previa" if com["exacto"] else f_c})
        com["usd_sorteos"] = round(com["sorteos_excluidos"] / 1000 * pr_c, 2)

        if con_ia:
            pr_ia, f_ia = costos.precio("clasif_opus")
            c_ia = com["n"] / 1000 * pr_ia
            costo += c_ia
            lineas.append({"k": "Clasificación con IA", "n": com["n"], "usd": round(c_ia, 2),
                           "precio": "US$ %.2f /1.000" % pr_ia, "fuente": f_ia})

    # La banda de incertidumbre depende de si medimos ESTAS marcas — no de si existe
    # alguna corrida previa de cualquier cosa. Se pondera por volumen: si el 80% de los
    # posteos estimados viene de marcas que nunca medimos, la banda es casi la de una
    # primera corrida, aunque una marca conocida esté en la lista.
    vol_supuesto = sum(f["posts_ig"] + f["posts_fb"] for f in filas if f["supuesto"])
    vol_total = max(tot_ig + tot_fb, 1)
    frac_supuesta = vol_supuesto / vol_total
    banda = (costos.BANDA_CON_HISTORIA
             + frac_supuesta * (costos.BANDA_SIN_HISTORIA - costos.BANDA_CON_HISTORIA))
    hay_hist = bool(hist)

    return {
        "filas": filas,
        "lineas": lineas,
        "posts_ig": tot_ig, "posts_fb": tot_fb,
        "comentarios": com,
        "costo_total": round(costo, 2),
        "costo_min": round(costo * (1 - banda), 2),
        "costo_max": round(costo * (1 + banda), 2),
        "banda_pct": int(banda * 100),
        "hay_historico": hay_hist,
        "marcas_supuestas": [f["marca"] for f in filas if f["supuesto"]],
        "gasto_acumulado": costos.gasto_total(),
    }


def _historico():
    """Cadencia real por marca, si ya se corrió alguna vez. Convierte supuestos en datos."""
    ruta = os.path.join(RAW_DIR, "posts.jsonl")
    if not os.path.exists(ruta):
        return {}
    try:
        posts = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]
        perf = json.load(open(os.path.join(RAW_DIR, "profiles.json"), encoding="utf-8"))
        dias = perf["ventana"]["dias"]
        cnt = collections.Counter(p["marca"] for p in posts if p["red"] == "Instagram")
        return {m: {"cadencia": n / (dias / 7.0)} for m, n in cnt.items()}
    except Exception:
        return {}


def _comentarios_reales(marcas):
    """Comentarios NO-sorteo que existen de verdad, SOLO para las marcas pedidas.

    Devuelve None si alguna de esas marcas no está en la captura previa: en ese caso
    no hay conteo exacto que dar, y hay que estimar. Antes esto devolvía el total de
    la captura sin mirar de qué marcas era — o sea, le daba a una marca nueva el
    número de otra. Un estimado equivocado es peor que un estimado con banda ancha.
    """
    ruta = os.path.join(RAW_DIR, "posts.jsonl")
    if not os.path.exists(ruta) or not marcas:
        return None
    try:
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
        pat = re.compile(cfg["comentarios"]["patron_sorteo"], re.I)
        posts = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]
        capturadas = {p["marca"] for p in posts if p["red"] == "Instagram"}
        if not set(marcas).issubset(capturadas):
            return None          # hay marcas que nunca medimos: no hay conteo exacto
        ig = [p for p in posts if p["red"] == "Instagram" and p["marca"] in marcas]
        tope = cfg["comentarios"]["por_posteo"]
        reales = sum(min(p["comments"], tope) for p in ig if not pat.search(p.get("texto") or ""))
        sorteos = sum(p["comments"] for p in ig if pat.search(p.get("texto") or ""))
        return reales, sorteos
    except Exception:
        return None


# ────────────────────────────────────────────────── corrida

def correr(cuentas, redes, dias, con_comentarios, con_ia):
    """Ejecuta el pipeline completo en un hilo, reportando el paso actual."""
    ESTADO.update({"corriendo": True, "paso": "Preparando…", "log": [], "fin": None, "error": None})
    try:
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
        cfg["ventana_dias"] = dias
        # Las cuentas que eligió el usuario reemplazan a las de la config.
        cfg["brands"] = [{
            "n": c["n"], "star": c.get("star", False),
            "ig": c.get("ig") if "ig" in redes else None,
            "fb": c.get("fb") if "fb" in redes else None,
            "tt": c.get("tt") if "tt" in redes else None,
        } for c in cuentas]
        json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        env = dict(os.environ)
        config_local.cargar()
        env["APIFY_TOKEN"] = config_local.obtener("APIFY_TOKEN")
        if config_local.obtener("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = config_local.obtener("ANTHROPIC_API_KEY")

        pasos = [("Bajando posteos de las redes…", [sys.executable, "fetch_apify.py",
                                                    "--dias", str(dias),
                                                    "--redes", ",".join(redes)])]
        if con_comentarios:
            pasos.append(("Bajando comentarios (sin sorteos)…", [sys.executable, "fetch_comments.py"]))
            if con_ia:
                pasos.append(("Leyendo el sentimiento con IA…", [sys.executable, "sentimiento.py"]))
        pasos.append(("Calculando métricas…",
                      [sys.executable, "analyze.py"] + (["--ia"] if con_ia else [])))
        if con_comentarios and con_ia:
            pasos.append(("Cruzando léxico rioplatense × IA…",
                          [sys.executable, "reporte_sentimiento.py"]))
        pasos.append(("Armando el PPT…", [sys.executable, "informe_ppt.py"]))

        for etiqueta, cmd in pasos:
            ESTADO["paso"] = etiqueta
            log("▸ " + etiqueta)
            p = subprocess.run(cmd, cwd=HERE, env=env, capture_output=True, text=True)
            for l in (p.stdout or "").strip().splitlines()[-14:]:
                log("   " + l)
            if p.returncode != 0:
                err = (p.stderr or "").strip().splitlines()
                for l in err[-6:]:
                    log("   ⚠ " + l)
                raise RuntimeError("Falló: %s" % etiqueta)

        ESTADO["paso"] = "Listo"
        ESTADO["fin"] = _resultado()
        log("✓ Terminado.")
    except Exception as e:
        ESTADO["error"] = str(e)
        log("✗ " + str(e))
    finally:
        ESTADO["corriendo"] = False


def _resultado():
    try:
        d = json.load(open(os.path.join(HERE, "monitor.json"), encoding="utf-8"))
        ppt = os.path.join(HERE, "Informe_Ciudadana.pptx")
        return {
            "posts": d["meta"]["total_posts"],
            "comentarios": d["meta"].get("comentarios", 0),
            "marcas": d["meta"]["marcas_activas"],
            "alertas": d["alertas"],
            "ppt": os.path.exists(ppt),
        }
    except Exception:
        return None


# ────────────────────────────────────────────────── servidor

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass    # sin ruido en la consola

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _archivo(self, ruta, tipo):
        if not os.path.exists(ruta):
            self.send_error(404)
            return
        b = open(ruta, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(b)))
        if tipo.startswith("application/vnd"):
            self.send_header("Content-Disposition",
                             'attachment; filename="Informe_Ciudadana.pptx"')
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        r = urlparse(self.path).path
        if r in ("/", "/index.html"):
            return self._archivo(os.path.join(HERE, "app.html"), "text/html; charset=utf-8")
        if r == "/logo.png":
            return self._archivo(os.path.join(HERE, "brand", "logo-ciudadana.png"), "image/png")
        if r == "/api/estado":
            cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
            return self._json({
                "credenciales": config_local.estado(),
                "cuentas": [b for b in cfg["brands"]],
                "categoria": cfg["categoria"],
                "corrida": {k: ESTADO[k] for k in ("corriendo", "paso", "log", "fin", "error")},
            })
        if r == "/tablero":
            return self._archivo(os.path.join(HERE, "index.html"), "text/html; charset=utf-8")
        if r == "/monitor.data.js":
            return self._archivo(os.path.join(HERE, "monitor.data.js"),
                                 "application/javascript; charset=utf-8")
        if r == "/descargar/ppt":
            return self._archivo(
                os.path.join(HERE, "Informe_Ciudadana.pptx"),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        self.send_error(404)

    def do_POST(self):
        r = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or "{}")

        if r == "/api/credenciales":
            config_local.guardar({k: v for k, v in body.items() if v})
            return self._json({"ok": True, "credenciales": config_local.estado()})

        if r == "/api/estimar":
            return self._json(estimar(body["cuentas"], body["redes"], int(body["dias"]),
                                      bool(body.get("comentarios")), bool(body.get("ia"))))

        if r == "/api/correr":
            if ESTADO["corriendo"]:
                return self._json({"error": "Ya hay una corrida en curso."}, 409)
            if not config_local.obtener("APIFY_TOKEN"):
                return self._json({"error": "Falta el token de Apify."}, 400)
            threading.Thread(target=correr, daemon=True, kwargs={
                "cuentas": body["cuentas"], "redes": body["redes"],
                "dias": int(body["dias"]), "con_comentarios": bool(body.get("comentarios")),
                "con_ia": bool(body.get("ia")),
            }).start()
            return self._json({"ok": True})

        self.send_error(404)


def main():
    srv = HTTPServer(("127.0.0.1", PUERTO), Handler)   # solo local: nadie de afuera entra
    url = "http://127.0.0.1:%d" % PUERTO
    print("\n  Monitor de categoría  ·  %s" % url)
    print("  (para cerrarlo: Ctrl+C)\n")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")


if __name__ == "__main__":
    main()
