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

import os, sys, json, re, time, threading, webbrowser, subprocess, collections
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config_local  # noqa: E402
import costos  # noqa: E402
import auth  # noqa: E402

CONFIG_PATH = os.path.join(HERE, "monitor.config.json")
CONSULTAS = os.path.join(HERE, "raw", "consultas.json")


def _consultas_leer():
    if not os.path.exists(CONSULTAS):
        return []
    try:
        return json.load(open(CONSULTAS, encoding="utf-8"))
    except Exception:
        return []


def _consulta_guardar(quien, body):
    """Registra los parámetros de una corrida para poder repetirla sin retipear.

    Se guarda todo lo necesario para relanzar: marcas, redes, período, comentarios,
    IA y muestra. Se deduplica por firma (misma consulta no se anota dos veces)."""
    import time as _t
    reg = {"cuando": _t.strftime("%Y-%m-%d %H:%M"), "quien": quien,
           "categoria": (body.get("categoria") or "").strip() or _categoria_de(body["cuentas"]),
           "cuentas": body["cuentas"], "redes": body["redes"], "dias": int(body["dias"]),
           "comentarios": bool(body.get("comentarios")), "ia": bool(body.get("ia")),
           "muestra": float(body.get("muestra", 1.0))}
    firma = json.dumps([reg["cuentas"], reg["redes"], reg["dias"],
                        reg["comentarios"], reg["ia"], reg["muestra"]], sort_keys=True)
    prev = [c for c in _consultas_leer()
            if json.dumps([c["cuentas"], c["redes"], c["dias"], c["comentarios"],
                           c["ia"], c.get("muestra", 1.0)], sort_keys=True) != firma]
    prev.insert(0, reg)
    os.makedirs(os.path.dirname(CONSULTAS), exist_ok=True)
    json.dump(prev[:30], open(CONSULTAS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def _categoria_de(cuentas):
    ppal = next((c["n"] for c in cuentas if c.get("star")), None)
    otras = [c["n"] for c in cuentas if not c.get("star")]
    return "%s vs %s" % (ppal or "?", ", ".join(otras[:3])) if otras else (ppal or "?")
RAW_DIR = os.path.join(HERE, "raw")
# En la nube el puerto lo asigna el host (Render/Fly usan PORT). Local: 8765.
PUERTO = int(os.environ.get("PORT") or os.environ.get("JAVIA_PUERTO") or 8765)
EN_NUBE = bool(os.environ.get("PORT") or os.environ.get("JAVIA_PUERTO"))

# Los precios ya no viven acá: costos.py los tiene verificados contra la facturación
# real, y si hay corridas previas usa el promedio medido en vez de una constante.

# Estado de la corrida en curso (lo lee el front por polling).
ESTADO = {"corriendo": False, "paso": "", "paso_num": 0, "pasos": [], "pasos_total": 0,
          "log": [], "fin": None, "error": None, "error_tipo": None,
          "inicio": 0, "eta_min": 0}


def log(msg):
    ESTADO["log"].append(msg)
    print(msg, flush=True)


# ────────────────────────────────────────────────── estimación

def estimar(cuentas, redes, dias, con_comentarios, con_ia=True, muestra=1.0):
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

    filas, tot_ig, tot_fb, tot_x, tot_tt = [], 0, 0, 0, 0
    for c in cuentas:
        cad = hist.get(c["n"], {}).get("cadencia")
        supuesto = cad is None
        cad = cad if cad is not None else costos.CADENCIA_DEFECTO
        p_ig = int(cad * semanas) if (c.get("ig") and "ig" in redes) else 0
        p_fb = int(cad * semanas * costos.CADENCIA_FB_FACTOR) if (c.get("fb") and "fb" in redes) else 0
        # En X la cadencia de marca suele ser bastante menor que en IG.
        p_x = int(cad * semanas * 0.6) if (c.get("x") and "x" in redes) else 0
        p_tt = int(cad * semanas * 0.5) if (c.get("tt") and "tt" in redes) else 0
        tot_ig += p_ig
        tot_fb += p_fb
        tot_x += p_x
        tot_tt += p_tt
        filas.append({"marca": c["n"], "posts_ig": p_ig, "posts_fb": p_fb, "posts_x": p_x,
                      "posts_tt": p_tt, "supuesto": supuesto})

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
    if tot_tt:
        pr_tt, f_tt = costos.precio("tt_post")
        c_tt = tot_tt / 1000 * pr_tt
        costo += c_tt
        lineas.append({"k": "Posteos de TikTok", "n": tot_tt, "usd": round(c_tt, 2),
                       "precio": "US$ %.2f /1.000" % pr_tt, "fuente": f_tt})
    if tot_x:
        pr_x, f_x = costos.precio("x_post")
        c_x = tot_x / 1000 * pr_x
        costo += c_x
        lineas.append({"k": "Posteos de X / Twitter", "n": tot_x, "usd": round(c_x, 2),
                       "precio": "US$ %.2f /1.000" % pr_x, "fuente": f_x})

    com = {"n": 0, "exacto": False}
    if con_comentarios:
        # Ahora se bajan comentarios de TODAS las redes, no solo Instagram. Cada red tiene
        # su actor y su precio. El conteo exacto (de la captura previa) solo vale para las
        # marcas realmente capturadas EN ESA RED; si falta alguna, esa red se estima.
        def _vol(red_nombre, flag, factor_est, tot_posts):
            marcas_r = [c["n"] for c in cuentas if c.get(flag) and flag in redes]
            if not marcas_r:
                return 0, True
            reales = _comentarios_por_red(marcas_r, red_nombre)
            if reales is not None:
                return reales, True
            return int(tot_posts * factor_est), False   # sin captura: estimación declarada

        ig_com, ig_ex = _vol("Instagram", "ig", 5, tot_ig)
        fb_com, fb_ex = _vol("Facebook", "fb", 4, tot_fb)
        tt_com, tt_ex = _vol("TikTok", "tt", 8, tot_tt)
        # X va por búsqueda 'to:handle', con tope chico por marca: se estima conservador.
        marcas_x = [c["n"] for c in cuentas if c.get("x") and "x" in redes]
        x_com = min(int(tot_x * 3), 60 * len(marcas_x)) if marcas_x else 0

        com["exacto"] = ig_ex and fb_ex and tt_ex and (ig_com + fb_com + tt_com > 0)
        com["total"] = ig_com + fb_com + tt_com + x_com
        # La muestra reduce la descarga por posteo (IG+FB+TT); X no se muestrea (es marginal).
        ig_p = int(round(ig_com * muestra))
        fb_p = int(round(fb_com * muestra))
        tt_p = int(round(tt_com * muestra))
        com["n"] = ig_p + fb_p + tt_p + x_com
        com["muestra"] = muestra

        pr_ig, _ = costos.precio("ig_comment")
        pr_fb, _ = costos.precio("fb_comment")
        pr_tt, _ = costos.precio("tt_comment")
        pr_x, _ = costos.precio("x_comment")
        c_com = (ig_p / 1000 * pr_ig + fb_p / 1000 * pr_fb
                 + tt_p / 1000 * pr_tt + x_com / 1000 * pr_x)
        costo += c_com
        detalle = " · ".join(x for x in [
            "IG %d" % ig_p if ig_p else "",
            "FB %d" % fb_p if fb_p else "",
            "TT %d" % tt_p if tt_p else "",
            "X %d" % x_com if x_com else ""] if x)
        etiqueta = "Comentarios (%s)" % detalle if detalle else "Comentarios"
        if muestra < 0.999:
            etiqueta += " · muestra %d%%" % round(muestra * 100)
        lineas.append({"k": etiqueta, "n": com["n"], "usd": round(c_com, 2),
                       "precio": "IG %.2f · FB %.2f · TT %.2f · X %.2f /1.000" % (pr_ig, pr_fb, pr_tt, pr_x),
                       "fuente": "conteo exacto de la captura previa" if com["exacto"]
                                 else "volumen estimado (sin captura previa)"})

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
    vol_supuesto = sum(f["posts_ig"] + f["posts_fb"] + f.get("posts_x", 0) + f.get("posts_tt", 0)
                       for f in filas if f["supuesto"])
    vol_total = max(tot_ig + tot_fb + tot_x + tot_tt, 1)
    frac_supuesta = vol_supuesto / vol_total
    banda = (costos.BANDA_CON_HISTORIA
             + frac_supuesta * (costos.BANDA_SIN_HISTORIA - costos.BANDA_CON_HISTORIA))
    hay_hist = bool(hist)

    # ¿Cuánto costaría procesando TODO? Con eso el front decide si ofrecer la opción de
    # muestra (umbral US$ 100). Ofrecer, no imponer: por defecto se hace todo.
    costo_full = costo
    if con_comentarios and com.get("muestra", 1.0) < 0.999:
        extra = com["total"] - com["n"]
        pr_c, _ = costos.precio("ig_comment")
        costo_full = costo + extra / 1000 * pr_c
        if con_ia:
            pr_ia, _ = costos.precio("clasif_opus")
            costo_full += extra / 1000 * pr_ia

    return {
        "filas": filas,
        "lineas": lineas,
        "costo_full": round(costo_full, 2),
        "ofrecer_muestra": costo_full > 100 and con_comentarios,
        "posts_ig": tot_ig, "posts_fb": tot_fb, "posts_x": tot_x,
        "comentarios": com,
        "costo_total": round(costo, 2),
        "costo_min": round(costo * (1 - banda), 2),
        "costo_max": round(costo * (1 + banda), 2),
        "banda_pct": int(banda * 100),
        "hay_historico": hay_hist,
        "marcas_supuestas": [f["marca"] for f in filas if f["supuesto"]],
        "gasto_acumulado": costos.gasto_total(),
        "eta_min": _eta(tot_ig, tot_fb, tot_x, com["n"] if con_comentarios else 0, con_ia),
    }


def _eta(ig, fb, x, coments, con_ia):
    """Minutos estimados de corrida. Calibrado con las corridas reales.

    El usuario necesita saber cuánto va a tardar: si no, interrumpe el proceso a los tres
    minutos creyendo que se colgó, y pierde lo que ya está scrapeado (y pago).
    """
    m = 1.0                                   # arranque
    m += (ig + fb + x) / 220.0                # scraping: ~220 posteos por minuto
    m += coments / 300.0                      # comentarios
    if con_ia and coments:
        m += coments / 90.0                   # clasificación con Claude (lotes de 60)
    m += 2.0                                  # análisis + informe + PDF
    return max(2, int(round(m)))


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
    """Comentarios que existen de verdad, SOLO para las marcas pedidas.

    Devuelve None si alguna de esas marcas no está en la captura previa: en ese caso
    no hay conteo exacto que dar, y hay que estimar. Antes esto devolvía el total de
    la captura sin mirar de qué marcas era — o sea, le daba a una marca nueva el
    número de otra. Un estimado equivocado es peor que un estimado con banda ancha.
    """
    return _comentarios_por_red(marcas, "Instagram")


def _comentarios_por_red(marcas, red):
    """Conteo exacto de comentarios (con el tope por posteo) de esas marcas en esa red.

    Devuelve None si alguna de las marcas no está capturada en esa red: sin captura no
    hay conteo exacto, hay que estimar. Un estimado con banda ancha es mejor que darle a
    una marca el número de otra.
    """
    ruta = os.path.join(RAW_DIR, "posts.jsonl")
    if not os.path.exists(ruta) or not marcas:
        return None
    try:
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
        posts = [json.loads(l) for l in open(ruta, encoding="utf-8") if l.strip()]
        capturadas = {p["marca"] for p in posts if p["red"] == red}
        if not set(marcas).issubset(capturadas):
            return None
        sel = [p for p in posts if p["red"] == red and p["marca"] in marcas]
        tope = cfg["comentarios"]["por_posteo"]
        return sum(min(p["comments"], tope) for p in sel)
    except Exception:
        return None


# ────────────────────────────────────────────────── corrida

# Firmas de error de las APIs. Sirven para decirle al usuario QUÉ pasó y QUÉ hacer,
# en vez de escupirle un stack trace que no puede accionar.
FIRMAS = [
    ("sin_creditos_anthropic", ("credit balance is too low", "insufficient_quota",
                                "billing", "purchase credits")),
    ("sin_creditos_apify",     ("monthly usage", "usage limit", "not enough credit",
                                "insufficient funds", "payment required", "402")),
    ("credencial_invalida",    ("authentication_error", "invalid api key", "unauthorized",
                                "rechazó el token", "401", "403")),
]


def _clasificar_error(texto):
    t = (texto or "").lower()
    # Anthropic primero: su mensaje de saldo también contiene "usage".
    for tipo, claves in FIRMAS:
        if any(k in t for k in claves):
            return tipo
    return None


def correr(cuentas, redes, dias, con_comentarios, con_ia, con_informe=True, eta_min=8, reanudar=False, muestra=1.0, categoria=None):
    """Ejecuta el pipeline completo en un hilo, reportando el paso actual."""
    ESTADO.update({"corriendo": True, "paso": "Preparando…", "paso_num": 0,
                   "log": [], "fin": None, "error": None, "error_tipo": None,
                   "inicio": time.time(), "eta_min": eta_min,
                   "flags": {"comentarios": con_comentarios, "ia": con_ia, "informe": con_informe}})
    try:
        # Al reanudar se reusa la config que quedó de la corrida fallida: no se rearman
        # las marcas ni se reescribe nada (los datos scrapeados siguen siendo válidos).
        if not reanudar:
            cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
            cfg["ventana_dias"] = dias
            if categoria:
                cfg["categoria"] = categoria
            cfg["brands"] = [{
                "n": c["n"], "star": c.get("star", False),
                "ig": c.get("ig") if "ig" in redes else None,
                "fb": c.get("fb") if "fb" in redes else None,
                "x": c.get("x") if "x" in redes else None,
                "tt": c.get("tt") if "tt" in redes else None,
            } for c in cuentas]
            json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        env = dict(os.environ)
        config_local.cargar()
        env["APIFY_TOKEN"] = config_local.obtener("APIFY_TOKEN")
        if config_local.obtener("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = config_local.obtener("ANTHROPIC_API_KEY")

        R = os.path.join(RAW_DIR, "")
        pasos = [("Bajando posteos de las redes", [sys.executable, "fetch_apify.py",
                                                   "--dias", str(dias),
                                                   "--redes", ",".join(redes)],
                  os.path.join(RAW_DIR, "posts.jsonl"))]
        if con_comentarios:
            # Los comentarios se bajan SOLO de las redes que el usuario eligió, no de
            # todo lo que haya en la captura (que puede tener redes de corridas previas).
            cmd_com = [sys.executable, "fetch_comments.py", "--redes", ",".join(redes)]
            if muestra < 0.999:
                cmd_com += ["--muestra", str(muestra)]
            pasos.append(("Bajando comentarios del público", cmd_com,
                          os.path.join(RAW_DIR, "comments.jsonl")))
            if con_ia:
                pasos.append(("Analizando el sentimiento", [sys.executable, "sentimiento.py"],
                              os.path.join(RAW_DIR, "comments_scored.jsonl")))
        pasos.append(("Calculando métricas",
                      [sys.executable, "analyze.py"] + (["--ia"] if con_ia else []), None))
        if con_comentarios and con_ia:
            pasos.append(("Cruzando léxico rioplatense con IA",
                          [sys.executable, "reporte_sentimiento.py"], None))
            pasos.append(("Generando las nubes de palabras", [sys.executable, "nubes.py"], None))
        if con_informe:
            pasos.append(("Armando el informe", [sys.executable, "informe_ppt.py"], None))
            pasos.append(("Verificando el diseño", [sys.executable, "verificar_ppt.py"], None))
            pasos.append(("Exportando a PDF", [sys.executable, "exportar_pdf.py"], None))

        ESTADO["pasos"] = [p[0] for p in pasos]
        ESTADO["pasos_total"] = len(pasos)

        # Marca de inicio para el FRENO EN VIVO: de acá en más se mide el gasto REAL,
        # no la estimación. Una estimación puede quedarse corta (categoría viral); el
        # gasto real, no. Los pasos que gastan (Apify, Claude) escriben en el libro.
        _cap = auth.TOPE_CORRIDA
        _ini_gasto = costos.cantidad_registros()

        for i, (etiqueta, cmd, out) in enumerate(pasos):
            ESTADO["paso_num"] = i
            # Reanudar: si el resultado de este paso ya está, no se rehace (no se re-paga).
            if reanudar and out and os.path.exists(out):
                log("↷ %s — ya estaba hecho, se reutiliza" % etiqueta)
                ESTADO["paso_num"] = i + 1
                continue
            # Antes de cada paso: ¿el gasto REAL de esta corrida ya se pasó del tope?
            real = costos.gasto_desde(_ini_gasto)
            if real > _cap:
                ESTADO["error_tipo"] = "tope_superado"
                for l in ["Gasto real de esta corrida: USD %.2f" % real,
                          "Tope por corrida: USD %.2f" % _cap]:
                    log("   " + l)
                raise RuntimeError("Se cortó por gasto: USD %.2f supera el tope de USD %.2f"
                                   % (real, _cap))
            ESTADO["paso"] = etiqueta
            log("▸ " + etiqueta)
            p = subprocess.run(cmd, cwd=HERE, env=env, capture_output=True, text=True)
            salida = (p.stdout or "") + "\n" + (p.stderr or "")
            for l in (p.stdout or "").strip().splitlines()[-12:]:
                log("   " + l)
            if p.returncode != 0:
                for l in (p.stderr or "").strip().splitlines()[-6:]:
                    log("   ⚠ " + l)
                ESTADO["error_tipo"] = _clasificar_error(salida)
                raise RuntimeError("Falló en: %s" % etiqueta)
            # Un paso puede "pasar" pero haber perdido la IA por falta de saldo:
            # eso hay que decirlo, no dejarlo escondido en el log.
            tipo = _clasificar_error(p.stderr or "")
            if tipo:
                ESTADO["error_tipo"] = tipo
                raise RuntimeError("Falló en: %s" % etiqueta)
            ESTADO["paso_num"] = i + 1

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
        pdf = os.path.join(HERE, "Informe_Ciudadana.pdf")
        return {
            "posts": d["meta"]["total_posts"],
            "comentarios": d["meta"].get("comentarios", 0),
            "marcas": d["meta"]["marcas_activas"],
            "alertas": d["alertas"],
            "ppt": os.path.exists(ppt),
            "pdf": os.path.exists(pdf),
        }
    except Exception:
        return None


# ────────────────────────────────────────────────── servidor

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass    # sin ruido en la consola

    # ── sesión
    def quien(self):
        """Quién es el que pide, según la cookie firmada. None si no está logueado."""
        cookies = self.headers.get("Cookie") or ""
        for c in cookies.split(";"):
            k, _, v = c.strip().partition("=")
            if k == "javia":
                return auth.leer_cookie(v)
        return None

    def _login_requerido(self):
        """Público: solo el login y el logo. Todo lo demás pide sesión."""
        r = urlparse(self.path).path
        return r not in ("/login", "/api/login", "/logo.png")

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
        if tipo.startswith("application/vnd") or tipo == "application/pdf":
            ext = "pdf" if tipo == "application/pdf" else "pptx"
            self.send_header("Content-Disposition",
                             'attachment; filename="Informe_Ciudadana.%s"' % ext)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        r = urlparse(self.path).path
        if self._login_requerido() and not self.quien():
            if r.startswith("/api/"):
                return self._json({"error": "sesión vencida", "login": True}, 401)
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if r == "/login":
            return self._archivo(os.path.join(HERE, "login.html"), "text/html; charset=utf-8")
        if r in ("/", "/index.html"):
            return self._archivo(os.path.join(HERE, "app.html"), "text/html; charset=utf-8")
        if r == "/salir":
            self.send_response(302)
            self.send_header("Set-Cookie", "javia=; Path=/; Max-Age=0")
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if r == "/logo.png":
            return self._archivo(os.path.join(HERE, "brand", "logo-ciudadana.png"), "image/png")
        if r == "/api/consultas":
            return self._json({"consultas": _consultas_leer()})
        if r == "/api/estado":
            cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
            return self._json({
                "quien": self.quien(),
                "gasto": auth.estado_gasto(),
                "credenciales": config_local.estado(),
                "cuentas": [b for b in cfg["brands"]],
                "categoria": cfg["categoria"],
                "corrida": {k: ESTADO[k] for k in
                            ("corriendo", "paso", "paso_num", "pasos", "pasos_total",
                             "log", "fin", "error", "error_tipo", "inicio", "eta_min")},
                "puede_reanudar": bool(ESTADO.get("error")
                                       and os.path.exists(os.path.join(RAW_DIR, "posts.jsonl"))),
            })
        if r == "/tablero":
            return self._archivo(os.path.join(HERE, "index.html"), "text/html; charset=utf-8")
        if r == "/monitor.data.js":
            return self._archivo(os.path.join(HERE, "monitor.data.js"),
                                 "application/javascript; charset=utf-8")
        if r == "/descargar/pdf":
            return self._archivo(os.path.join(HERE, "Informe_Ciudadana.pdf"),
                                 "application/pdf")
        if r == "/descargar/ppt":
            return self._archivo(
                os.path.join(HERE, "Informe_Ciudadana.pptx"),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        self.send_error(404)

    def do_POST(self):
        r = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or "{}")

        if r == "/api/login":
            if not auth.verificar_password(body.get("password")):
                time.sleep(1.0)          # frena el fuerza bruta
                return self._json({"error": "Contraseña incorrecta."}, 401)
            quien = (body.get("quien") or "equipo").strip()[:40] or "equipo"
            cookie = auth.crear_cookie(quien)
            b = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie",
                             "javia=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d"
                             % (cookie, auth.DURACION))
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return

        if self._login_requerido() and not self.quien():
            return self._json({"error": "sesión vencida", "login": True}, 401)

        if r == "/api/credenciales":
            config_local.guardar({k: v for k, v in body.items() if v})
            return self._json({"ok": True, "credenciales": config_local.estado()})

        if r == "/api/estimar":
            return self._json(estimar(body["cuentas"], body["redes"], int(body["dias"]),
                                      bool(body.get("comentarios")), bool(body.get("ia")),
                                      float(body.get("muestra", 1.0))))

        if r == "/api/reanudar":
            if ESTADO["corriendo"]:
                return self._json({"error": "Ya hay una corrida en curso."}, 409)
            # Reanudar reusa lo scrapeado: no re-paga Apify. Solo corre lo que faltó.
            if not os.path.exists(os.path.join(RAW_DIR, "posts.jsonl")):
                return self._json({"error": "No hay datos guardados para reanudar. "
                                   "El servidor pudo haberse reiniciado; hay que correr de nuevo."}, 400)
            fl = ESTADO.get("flags") or {"comentarios": True, "ia": True, "informe": True}
            threading.Thread(target=correr, daemon=True, kwargs={
                "cuentas": [], "redes": [], "dias": 0,
                "con_comentarios": fl["comentarios"], "con_ia": fl["ia"],
                "con_informe": fl["informe"], "reanudar": True, "eta_min": 3,
            }).start()
            return self._json({"ok": True})

        if r == "/api/correr":
            if ESTADO["corriendo"]:
                return self._json({"error": "Ya hay una corrida en curso."}, 409)
            if not config_local.obtener("APIFY_TOKEN"):
                return self._json({"error": "Falta el token de Apify."}, 400)

            # El freno: se evalúa sobre el costo MÁXIMO estimado, no el promedio.
            est = estimar(body["cuentas"], body["redes"], int(body["dias"]),
                          bool(body.get("comentarios")), bool(body.get("ia")),
                          float(body.get("muestra", 1.0)))
            ok, motivo = auth.puede_correr(est["costo_max"])
            if not ok:
                return self._json({"error": motivo, "tope": True}, 402)
            auth.registrar_corrida(
                self.quien(), est["costo_max"],
                "%d marcas · %d días · %s" % (len(body["cuentas"]), int(body["dias"]),
                                              "+".join(body["redes"])))
            _consulta_guardar(self.quien(), body)
            threading.Thread(target=correr, daemon=True, kwargs={
                "cuentas": body["cuentas"], "redes": body["redes"],
                "dias": int(body["dias"]), "con_comentarios": bool(body.get("comentarios")),
                "con_ia": bool(body.get("ia")),
                "con_informe": bool(body.get("informe", True)),
                "eta_min": est.get("eta_min", 8),
                "muestra": float(body.get("muestra", 1.0)),
                "categoria": (body.get("categoria") or "").strip() or _categoria_de(body["cuentas"]),
            }).start()
            return self._json({"ok": True})

        self.send_error(404)


def main():
    if not auth.configurada():
        print("ERROR: falta la contraseña. La app no arranca sin ella.\n"
              "  Local:  export JAVIA_PASSWORD='tu-clave' && python3 app.py\n"
              "  Nube :  cargala como variable de entorno en el panel del host.\n"
              "  (No se guarda en el código: el repo es público.)", file=sys.stderr)
        return 1

    # Local: solo 127.0.0.1, nadie de afuera entra. En la nube hay que escuchar en
    # 0.0.0.0 para que el balanceador llegue — ahí el gate lo hace la contraseña.
    host = "0.0.0.0" if EN_NUBE else "127.0.0.1"
    srv = ThreadingHTTPServer((host, PUERTO), Handler)
    print("\n  JavIA · escuchando en %s:%d" % (host, PUERTO), flush=True)
    if not EN_NUBE:
        url = "http://127.0.0.1:%d" % PUERTO
        print("  %s   (Ctrl+C para cerrar)\n" % url)
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
