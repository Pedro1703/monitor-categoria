#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Credenciales — se configuran UNA vez y quedan.

Las keys viven en un archivo .env local, que está en .gitignore: nunca se suben al
repo (que es público). No hace falta exportarlas en cada terminal ni pegarlas de nuevo.

Orden de búsqueda: variable de entorno → .env. La variable gana, así podés pisar
una key puntualmente sin tocar el archivo.

Para configurarlas:  python3 configurar.py
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")

CLAVES = {
    "APIFY_TOKEN": {
        "desc": "Token de Apify (baja los posteos y comentarios)",
        "url": "https://console.apify.com/settings/integrations",
        "prefijo": "apify_api_",
        "requerida": True,
    },
    "JAVIA_PASSWORD": {
        "desc": "Contraseña de acceso a la herramienta",
        "url": "",
        "prefijo": "",
        "requerida": False,
    },
    "ANTHROPIC_API_KEY": {
        "desc": "API key de Claude (clasifica sentimiento y territorios)",
        "url": "https://console.anthropic.com/settings/keys",
        "prefijo": "sk-ant-",
        "requerida": False,   # sin ella el monitor igual corre, con reglas
    },
}


def _leer_env():
    if not os.path.exists(ENV_PATH):
        return {}
    datos = {}
    for linea in open(ENV_PATH, encoding="utf-8"):
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        datos[k.strip()] = v.strip().strip('"').strip("'")
    return datos


def cargar():
    """Mete las claves del .env en el entorno del proceso (sin pisar lo ya seteado)."""
    for k, v in _leer_env().items():
        if v and not os.environ.get(k):
            os.environ[k] = v


def obtener(clave):
    cargar()
    return os.environ.get(clave, "").strip()


def guardar(nuevas):
    """Escribe/actualiza el .env preservando lo que ya había."""
    datos = _leer_env()
    datos.update({k: v for k, v in nuevas.items() if v})
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("# Credenciales del Monitor de categoría.\n")
        f.write("# Este archivo NO se sube a git (está en .gitignore). No lo compartas.\n\n")
        for k, v in datos.items():
            f.write("%s=%s\n" % (k, v))
    os.chmod(ENV_PATH, 0o600)   # solo el dueño puede leerlo
    cargar()


def estado():
    """Qué credenciales hay, sin revelarlas."""
    cargar()
    out = {}
    for k, meta in CLAVES.items():
        v = os.environ.get(k, "").strip()
        out[k] = {
            "configurada": bool(v),
            "hint": (v[:len(meta["prefijo"]) + 4] + "…" + v[-4:]) if len(v) > 12 else "",
            "requerida": meta["requerida"],
            "desc": meta["desc"],
            "url": meta["url"],
        }
    return out
