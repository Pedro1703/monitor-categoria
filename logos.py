#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logos de las marcas — se bajan de la foto de perfil de Instagram y se recortan en círculo.

Por qué la foto de perfil: es el logo que la marca eligió mostrar, siempre está
actualizada, y viene de la misma captura que el resto de los datos. No hay que salir a
buscar assets a mano ni pedirle nada a nadie.

El recorte circular no es capricho: la Identidad Visual Ciudadana dice que las imágenes
van recortadas en formas geométricas (círculo, cápsula, rectángulo redondeado).

    python3 logos.py        # baja/actualiza los logos en brand/marcas/
"""

import os, sys, json, ssl, io, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
DIR = os.path.join(HERE, "brand", "marcas")

sys.path.insert(0, HERE)
import config_local  # noqa: E402
config_local.cargar()


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def circular(data, tam=400):
    """Recorta la imagen en círculo, con transparencia afuera."""
    from PIL import Image, ImageDraw
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    # Recorte al cuadrado central antes de redondear, para no deformar
    w, h = im.size
    lado = min(w, h)
    im = im.crop(((w - lado) // 2, (h - lado) // 2,
                  (w + lado) // 2, (h + lado) // 2)).resize((tam, tam), Image.LANCZOS)
    mask = Image.new("L", (tam * 4, tam * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, tam * 4, tam * 4), fill=255)
    mask = mask.resize((tam, tam), Image.LANCZOS)      # antialias del borde
    out = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def ruta(marca):
    """Dónde vive el logo de una marca (o None si no lo tenemos)."""
    p = os.path.join(DIR, "%s.png" % marca.lower().replace(" ", "_").replace("ó", "o"))
    return p if os.path.exists(p) else None


def bajar():
    fuente = os.path.join(RAW, "perfiles_full.json")
    if not os.path.exists(fuente):
        print("ERROR: falta raw/perfiles_full.json (lo genera fetch_apify.py)", file=sys.stderr)
        return 1
    perfiles = json.load(open(fuente, encoding="utf-8"))
    cfg = json.load(open(os.path.join(HERE, "monitor.config.json"), encoding="utf-8"))
    por_handle = {b["ig"].lower(): b["n"] for b in cfg["brands"] if b.get("ig")}

    os.makedirs(DIR, exist_ok=True)
    ctx, n = _ctx(), 0
    for p in perfiles:
        h = (p.get("username") or "").lower()
        marca = por_handle.get(h)
        url = p.get("profilePicUrlHD") or p.get("profilePicUrl")
        if not marca or not url:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=45, context=ctx).read()
            dest = os.path.join(DIR, "%s.png" % marca.lower().replace(" ", "_").replace("ó", "o"))
            circular(data).save(dest)
            print("  ✓ %-18s → %s" % (marca, os.path.basename(dest)))
            n += 1
        except Exception as e:
            print("  ✗ %-18s %s" % (marca, e), file=sys.stderr)
    print("\n%d logos en brand/marcas/" % n)
    return 0


if __name__ == "__main__":
    sys.exit(bajar())
