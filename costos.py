#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Libro de costos: registra lo que se gastó DE VERDAD, y estima con eso.

POR QUÉ
=======
Una estimación construida sobre supuestos envejece mal y nadie sabe cuánto errarle.
Acá cada corrida deja registrado su gasto real (items scrapeados, tokens consumidos,
dólares), y la próxima estimación usa ESE número en vez de una constante inventada.

O sea: el estimador aprende. La primera corrida es la única que estima a ciegas —
y lo dice explícitamente, en vez de fingir precisión.

Precios de referencia (fallback, cuando todavía no hay historia):
verificados contra la facturación real de Apify en jul-2026, plan Starter.
"""

import os, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIBRO = os.path.join(HERE, "raw", "costos.json")

# Precios unitarios de referencia. Los tres primeros están VERIFICADOS contra la
# facturación real: 892 posteos IG = US$2,054 → 2,30/1000. Ídem FB y comentarios.
PRECIOS = {
    "ig_post":      {"usd_1000": 2.30, "fuente": "verificado contra factura Apify (jul-2026)"},
    "fb_post":      {"usd_1000": 5.00, "fuente": "verificado contra factura Apify (jul-2026)"},
    "ig_comment":   {"usd_1000": 2.30, "fuente": "verificado contra factura Apify (jul-2026)"},
    "fb_comment":   {"usd_1000": 4.00, "fuente": "tarifa publicada del actor (sin verificar aún)"},
    "x_comment":    {"usd_1000": 0.40, "fuente": "mismo actor que x_post (sin verificar aún)"},
    "x_post":       {"usd_1000": 0.40, "fuente": "tarifa publicada del actor (sin verificar aún)"},
    "ig_profile":   {"usd_1000": 2.30, "fuente": "verificado"},
    # Claude: medido con count_tokens sobre un lote real (3.186 tok in + ~2.100 out
    # por cada 60 comentarios). Se le deja margen para los tokens de thinking.
    "clasif_opus":  {"usd_1000": 1.40, "fuente": "medido con count_tokens (Opus 4.8)"},
    "clasif_haiku": {"usd_1000": 0.30, "fuente": "medido con count_tokens (Haiku 4.5)"},
}

# Cadencia por defecto para la PRIMERA corrida, cuando no hay historia.
# Calibrada contra la corrida real de seguros UY: el promedio fue 2,32 posteos/semana
# en IG. Se deja 2,5 (levemente por encima) a propósito: en una estimación de costo,
# errar hacia arriba es prudente; errar hacia abajo es una factura sorpresa.
CADENCIA_DEFECTO = 2.5
CADENCIA_FB_FACTOR = 0.85     # en FB suelen postear algo menos que en IG

# Incertidumbre de la primera estimación, medida contra la corrida real (error +8%).
# Se muestra como rango para que nadie confunda un supuesto con un dato.
BANDA_SIN_HISTORIA = 0.45     # ±45%
BANDA_CON_HISTORIA = 0.15     # ±15% — la cadencia real igual varía mes a mes


def _leer():
    if not os.path.exists(LIBRO):
        return {"corridas": []}
    try:
        return json.load(open(LIBRO, encoding="utf-8"))
    except Exception:
        return {"corridas": []}


def registrar(concepto, items, usd, detalle=""):
    """Anota un gasto real. Lo llaman fetch_apify, fetch_comments y sentimiento."""
    libro = _leer()
    libro["corridas"].append({
        "cuando": time.strftime("%Y-%m-%d %H:%M"),
        "concepto": concepto, "items": items,
        "usd": round(usd, 4), "detalle": detalle,
    })
    os.makedirs(os.path.dirname(LIBRO), exist_ok=True)
    json.dump(libro, open(LIBRO, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def precio(concepto):
    """USD por 1.000 unidades. Usa el promedio REAL si ya hay historia."""
    libro = _leer()
    reales = [c for c in libro["corridas"] if c["concepto"] == concepto and c["items"] > 0]
    if reales:
        items = sum(c["items"] for c in reales)
        usd = sum(c["usd"] for c in reales)
        if items >= 50:                     # con menos de 50 items el promedio es ruidoso
            return usd / items * 1000, "medido en %d corrida(s) tuya(s)" % len(reales)
    p = PRECIOS.get(concepto, {"usd_1000": 0, "fuente": "desconocido"})
    return p["usd_1000"], p["fuente"]


def gasto_total():
    libro = _leer()
    return round(sum(c["usd"] for c in libro["corridas"]), 2)


def cantidad_registros():
    """Cuántos gastos hay anotados. Sirve para marcar el inicio de una corrida."""
    return len(_leer()["corridas"])


def gasto_desde(indice):
    """Gasto REAL acumulado desde un punto. Es el freno en vivo: no la estimación,
    lo que efectivamente se gastó hasta ahora en esta corrida."""
    libro = _leer()
    return round(sum(c["usd"] for c in libro["corridas"][indice:]), 2)


def historial():
    return _leer()["corridas"]
