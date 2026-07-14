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

CONFIG_PATH = os.path.join(HERE, "monitor.config.json")
RAW_DIR = os.path.join(HERE, "raw")
PUERTO = 8765

# Precios Apify (plan Starter). Se usan solo para estimar antes de gastar.
USD_1000_POSTS = 2.30
USD_1000_COMENTARIOS = 2.30
USD_1000_POSTS_FB = 5.00      # el actor de FB es más caro y más variable
# Claude clasificando: ~1.500 tokens por comentario ida y vuelta, Opus.
USD_1000_CLASIF = 1.80

# Estado de la corrida en curso (lo lee el front por polling).
ESTADO = {"corriendo": False, "paso": "", "log": [], "fin": None, "error": None}


def log(msg):
    ESTADO["log"].append(msg)
    print(msg, flush=True)


# ────────────────────────────────────────────────── estimación

def estimar(cuentas, redes, dias, con_comentarios):
    """Estima volumen y costo. NO gasta nada: son cuentas sobre supuestos declarados.

    El supuesto de cadencia (posteos/semana) es lo único que se adivina. Después de la
    primera corrida real el número deja de ser un supuesto: se lee del crudo.
    """
    semanas = dias / 7.0
    hist = _historico()

    filas, tot_posts_ig, tot_posts_fb = [], 0, 0
    for c in cuentas:
        cad = hist.get(c["n"], {}).get("cadencia")
        supuesto = cad is None
        cad = cad if cad is not None else 2.5   # supuesto por defecto: 2,5 posteos/semana
        n_redes_ig = 1 if (c.get("ig") and "ig" in redes) else 0
        n_redes_fb = 1 if (c.get("fb") and "fb" in redes) else 0
        p_ig = int(cad * semanas) * n_redes_ig
        p_fb = int(cad * semanas * 0.8) * n_redes_fb   # en FB suelen postear algo menos
        tot_posts_ig += p_ig
        tot_posts_fb += p_fb
        filas.append({"marca": c["n"], "posts_ig": p_ig, "posts_fb": p_fb, "supuesto": supuesto})

    costo = tot_posts_ig / 1000 * USD_1000_POSTS + tot_posts_fb / 1000 * USD_1000_POSTS_FB

    # Comentarios: si ya hay una corrida previa, sabemos cuántos hay DE VERDAD.
    com = {"n": 0, "costo": 0.0, "clasif": 0.0, "real": False, "sorteos_excluidos": 0}
    if con_comentarios:
        reales = _comentarios_reales(dias)
        if reales is not None:
            com["n"], com["sorteos_excluidos"] = reales
            com["real"] = True
        else:
            # Sin datos previos: 0,8 comentarios por posteo (la categoría conversa poquísimo).
            com["n"] = int(tot_posts_ig * 0.8)
        com["costo"] = com["n"] / 1000 * USD_1000_COMENTARIOS
        com["clasif"] = com["n"] / 1000 * USD_1000_CLASIF
        costo += com["costo"] + com["clasif"]

    return {
        "filas": filas,
        "posts_ig": tot_posts_ig, "posts_fb": tot_posts_fb,
        "comentarios": com,
        "costo_total": round(costo, 2),
        "hay_historico": bool(hist),
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


def _comentarios_reales(dias):
    """Cuántos comentarios NO-sorteo existen realmente, según la última captura."""
    ruta = os.path.join(RAW_DIR, "posts.jsonl")
    if not os.path.exists(ruta):
        return None
    try:
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
        pat = re.compile(cfg["comentarios"]["patron_sorteo"], re.I)
        posts = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]
        ig = [p for p in posts if p["red"] == "Instagram"]
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
                                      bool(body.get("comentarios"))))

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
