#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nlp_local.py — motor de sentimiento LOCAL y gratis, OPCIONAL.

Por qué existe
--------------
El clasificador principal del monitor es Claude (sentimiento.py): es el que mejor lee el
español rioplatense, la ironía y el voseo, y hoy es lo más cercano al estado del arte para
esta variante (hay investigación específica de LLMs sobre español rioplatense que lo
confirma). Pero Claude cuesta plata por token.

Este módulo agrega un SEGUNDO modelo entrenado, gratis y offline, para dos usos:
  1) Tercer voto en la validación cruzada (reporte_sentimiento.py): además del léxico y de
     Claude, un modelo entrenado de verdad. Cuanto más coinciden tres métodos independientes,
     más confiable el número.
  2) Motor gratis cuando no hay presupuesto de API (uso offline).

Qué modelo y por qué
--------------------
pysentimiento/robertuito-sentiment-analysis (RoBERTuito): un RoBERTa preentrenado con ~500
millones de tweets en español de MUCHOS países. Esa base multi-país es justamente lo que le
da sensibilidad a las variantes regionales (rioplatense, mexicano, etc.), a diferencia de un
modelo de español formal (BETO, MarIA) entrenado sobre Wikipedia/BOE. En los benchmarks de
TASS supera a BETO y a mBERT en sentimiento (Macro-F1 ~0.70).

Peso y despliegue
-----------------
NO viene instalado: `pip install pysentimiento` arrastra PyTorch (~1-2 GB) y los pesos del
modelo (~500 MB la primera vez). Por eso NO entra en el plan free de Render (512 MB de RAM):
esto es para correr LOCAL o en una instancia paga. Si no está instalado, `disponible()`
devuelve False y todo el pipeline sigue igual, sin tocar nada.

Alternativas evaluadas (ver NLP_MODELOS.md para el detalle):
  · BETO (dccuchile) — español general, menos social/coloquial.
  · XLM-T — multilingüe (30+ idiomas), más liviano en foco pero menos fino en español.
  · Léxico rioplatense propio (lexico_uy.py) — cero dependencias, ya es el fallback que
    corre en la nube. RoBERTuito es un escalón por encima cuando se puede instalar.
"""

import functools


def disponible():
    """True si pysentimiento está instalado. No baja el modelo (eso pasa al primer uso)."""
    try:
        import pysentimiento  # noqa: F401
        return True
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def _analyzer():
    # Se crea una sola vez: baja los pesos la primera vez (~500 MB) y los cachea.
    from pysentimiento import create_analyzer
    return create_analyzer(task="sentiment", lang="es")


_MAP = {"POS": "positivo", "NEU": "neutro", "NEG": "negativo"}


def sentimiento(textos):
    """Lista de textos → lista de 'positivo'|'neutro'|'negativo'.

    Devuelve [] si el modelo no está instalado (así el caller decide sin romperse).
    Procesa en lote: RoBERTuito acepta la lista completa de una.
    """
    textos = [t or "" for t in textos]
    if not textos or not disponible():
        return []
    salida = _analyzer().predict(textos)
    if not isinstance(salida, list):          # predict de un solo texto devuelve un objeto
        salida = [salida]
    return [_MAP.get(getattr(r, "output", None), "neutro") for r in salida]


if __name__ == "__main__":
    if not disponible():
        print("pysentimiento no está instalado.  pip install pysentimiento")
        raise SystemExit(0)
    pruebas = [
        "Excelente, solo 3 meses para resolverme el trámite",   # ironía → negativo
        "Gracias, me atendieron bárbaro en la sucursal",        # positivo
        "¿Tienen sucursal en Salto?",                           # neutro
    ]
    for t, s in zip(pruebas, sentimiento(pruebas)):
        print("  %-10s  %s" % (s, t))
