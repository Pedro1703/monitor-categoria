#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lexico_uy — analizador de sentimiento para español rioplatense (Uruguay).

POR QUÉ EXISTE, SI YA TENEMOS UN LLM
====================================
No reemplaza a Claude: lo AUDITA. Son dos métodos independientes, y su desacuerdo
es información. Donde los dos coinciden, el dato es sólido. Donde discrepan, casi
siempre hay ironía o una frase ambigua: esos comentarios se marcan para que los lea
un humano en vez de promediarlos a ciegas.

Además, a diferencia del LLM, este módulo es:
  · TRANSPARENTE — devuelve qué términos disparó cada score. Se puede defender en una
    reunión: "esto dio negativo por 'chanta' y por 'me dejaron sin auto'".
  · GRATIS y REPRODUCIBLE — mismo texto, mismo score, siempre. Sin costo de API.
  · AUDITABLE — el lexicón es un dict que se lee y se corrige a mano.

QUÉ MANEJA, QUE UN LEXICÓN GENÉRICO DE ESPAÑOL NO
=================================================
1. NEGACIÓN CON ALCANCE, incluida la DOBLE NEGACIÓN rioplatense:
     "no está nada mal"        → POSITIVO   (dos negaciones que se cancelan)
     "no me pagaron nunca"     → NEGATIVO reforzado (concordancia negativa: en español
                                 'no...nunca' NO se cancela, intensifica)
   Esta distinción es la que rompe a los lexicones portados del inglés, donde
   "not bad" = positivo pero "not never" es agramatical.

2. INTENSIFICADORES LOCALES: "re", "recontra", "mal" como intensificador
   ("está mal bueno" = muy bueno), "un montón", "para nada" (invierte).

3. JERGA URUGUAYA con polaridad fuerte que ningún lexicón de España trae:
     chanta, cagador, de cuarta, gil, garca  → muy negativo
     bárbaro, joya, de diez, una masa, salado, zarpado, un caño → muy positivo

4. IRONÍA: marcadores como "sí, claro", "jaja" junto a términos negativos, elogio
   seguido de "pero", y el patrón "gracias por X, aunque Y".

5. EMOJIS con polaridad.

LIMITACIÓN QUE HAY QUE DECLARAR
===============================
Un lexicón no entiende contexto. "Me chocaron el auto" no tiene ninguna palabra
negativa y sin embargo es una queja. Por eso este módulo NO sustituye al LLM: lo
complementa. Su valor está en el acuerdo/desacuerdo, no en correr solo.

    from lexico_uy import analizar
    r = analizar("no está nada mal el servicio")
    r.sentimiento   -> "positivo"
    r.score         -> 0.42
    r.evidencia     -> [("mal", -0.6, "negado x2 → invertido")]
"""

import re
import unicodedata
from collections import namedtuple

Resultado = namedtuple("Resultado", "sentimiento score evidencia ironia")


# ══════════════════════════════════════════════════════════ lexicón

# Peso de -1 (muy negativo) a +1 (muy positivo).
LEXICON = {
    # ── Jerga uruguaya / rioplatense — negativa
    "chanta": -0.9, "chantas": -0.9, "cagador": -0.95, "cagadores": -0.95,
    "garca": -0.9, "garcas": -0.9, "gil": -0.7, "giles": -0.7,
    "verguenza": -0.8, "vergüenza": -0.8, "verguenzas": -0.8,
    "estafa": -0.95, "estafadores": -0.95, "robo": -0.85, "roban": -0.85,
    "ladrones": -0.9, "ladron": -0.9, "ladrón": -0.9, "chorros": -0.9, "chorro": -0.85,
    "desastre": -0.85, "horrible": -0.8, "pesimo": -0.9, "pésimo": -0.9,
    "malisimo": -0.85, "malísimo": -0.85, "espantoso": -0.8,
    "porqueria": -0.85, "porquería": -0.85, "basura": -0.85,
    "lamentable": -0.75, "penoso": -0.7, "deplorable": -0.8,
    "mentira": -0.7, "mentiras": -0.7, "mienten": -0.75, "miente": -0.75,
    "farsa": -0.85, "fraude": -0.9, "engaño": -0.8, "engañan": -0.8,
    "inutil": -0.7, "inútil": -0.7, "incompetentes": -0.8, "ineptos": -0.8,
    "abuso": -0.8, "abusan": -0.8, "impresentable": -0.8,
    "nefasto": -0.85, "asco": -0.85, "asqueroso": -0.85,
    "burla": -0.75, "burlan": -0.75, "tomadura": -0.75,
    "indignante": -0.8, "indignado": -0.75, "bronca": -0.7,
    "harto": -0.65, "harta": -0.65, "cansado": -0.5, "cansada": -0.5,
    "nunca": -0.25,          # suele venir en queja: "nunca me atendieron"
    "jamas": -0.3, "jamás": -0.3,
    "peor": -0.6, "peores": -0.6, "mal": -0.6, "mala": -0.55, "malo": -0.55,
    "problema": -0.45, "problemas": -0.5, "queja": -0.5, "quejas": -0.5,
    "reclamo": -0.4, "reclamos": -0.45, "reclamando": -0.5,
    "demora": -0.6, "demoras": -0.6, "demoran": -0.65, "demorando": -0.6,
    "espera": -0.35, "esperando": -0.5, "esperar": -0.4,
    "rechazaron": -0.8, "rechazo": -0.75, "rechazado": -0.75, "negaron": -0.75,
    "no cubre": -0.8, "no cubren": -0.8, "letra chica": -0.75,
    "aumento": -0.4, "aumentos": -0.45, "carisimo": -0.7, "carísimo": -0.7,
    "caro": -0.55, "cara": -0.4, "impagable": -0.75,
    "tramite": -0.25, "trámite": -0.25, "burocracia": -0.6, "burocratico": -0.6,
    "vueltas": -0.45, "vergonzoso": -0.85,
    "estafaron": -0.95, "afano": -0.85, "afanan": -0.85,
    "de cuarta": -0.85, "para el orto": -0.9, "una cagada": -0.85,
    "no sirve": -0.8, "no sirven": -0.8, "no funciona": -0.7, "no anda": -0.65,
    "no responden": -0.75, "no contestan": -0.75, "no atienden": -0.75,
    "nadie atiende": -0.8, "nadie responde": -0.8,

    # ── Jerga uruguaya / rioplatense — positiva
    "barbaro": 0.8, "bárbaro": 0.8, "joya": 0.8, "una masa": 0.85,
    "de diez": 0.85, "un caño": 0.8, "salado": 0.7, "zarpado": 0.75,
    "genial": 0.8, "genios": 0.75, "grosos": 0.8, "groso": 0.8,
    "excelente": 0.85, "excelentes": 0.85, "impecable": 0.85,
    "buenisimo": 0.85, "buenísimo": 0.85, "espectacular": 0.85,
    "increible": 0.75, "increíble": 0.75, "maravilloso": 0.85,
    "gracias": 0.55, "agradecido": 0.7, "agradecida": 0.7, "agradezco": 0.65,
    "felicitaciones": 0.8, "felicidades": 0.75, "felicito": 0.75,
    "orgullo": 0.75, "orgullosos": 0.75, "orgulloso": 0.7,
    "bien": 0.5, "bueno": 0.5, "buena": 0.5, "buenos": 0.5, "buenas": 0.45,
    "mejor": 0.55, "mejores": 0.6, "perfecto": 0.8, "perfecta": 0.8,
    "recomiendo": 0.8, "recomendable": 0.75, "recomendado": 0.7,
    "rapido": 0.55, "rápido": 0.55, "eficiente": 0.7, "eficientes": 0.7,
    "amables": 0.7, "amable": 0.7, "atentos": 0.65, "cordial": 0.6,
    "resolvieron": 0.75, "resolvio": 0.75, "resolvió": 0.75, "solucionaron": 0.75,
    "cumplieron": 0.75, "cumplen": 0.7, "respondieron": 0.6,
    "tranquilidad": 0.6, "confianza": 0.6, "seguridad": 0.4,
    "respaldo": 0.65, "respaldan": 0.65, "apoyo": 0.55, "apoyan": 0.55,
    "aplausos": 0.7, "grande": 0.5, "grandes": 0.45,
    "lindo": 0.6, "linda": 0.6, "hermoso": 0.7, "hermosa": 0.7,
    "exito": 0.6, "éxito": 0.6, "exitos": 0.6, "éxitos": 0.6,
    "feliz": 0.65, "felices": 0.65, "contento": 0.65, "contenta": 0.65,
    "satisfecho": 0.7, "satisfecha": 0.7, "conforme": 0.5,
    "impecables": 0.85, "profesionales": 0.6, "serios": 0.55,
    "correcto": 0.5, "correctos": 0.5, "cumplidores": 0.8,
    "siempre presente": 0.7, "siempre estan": 0.65, "siempre están": 0.65,
    "del lado correcto": 0.75,
}

# ── Emojis con carga
EMOJI = {
    "👏": 0.6, "🙌": 0.6, "❤️": 0.7, "♥": 0.6, "😍": 0.75, "🥰": 0.75,
    "💪": 0.5, "🎉": 0.6, "✨": 0.4, "🙏": 0.5, "😊": 0.6, "😁": 0.6,
    "🔥": 0.5, "👍": 0.6, "💙": 0.6, "🇺🇾": 0.3, "🏆": 0.6, "⭐": 0.5,
    "😢": -0.5, "😭": -0.6, "😡": -0.85, "🤬": -0.9, "👎": -0.8,
    "😠": -0.8, "🤡": -0.7, "💩": -0.85, "🙄": -0.5, "😒": -0.55,
    "😤": -0.6, "⚠️": -0.3, "❌": -0.5,
}

# ── Negadores. Alcance: las N palabras siguientes.
NEGADORES = {"no", "nunca", "jamas", "jamás", "ni", "nadie", "nada", "tampoco",
             "sin", "ningun", "ningún", "ninguna", "nunca más", "nunca mas"}
ALCANCE_NEG = 4

# ── Intensificadores (multiplican) y atenuadores
INTENSIFICADORES = {
    "muy": 1.5, "re": 1.6, "recontra": 1.9, "super": 1.6, "súper": 1.6,
    "mega": 1.7, "tan": 1.4, "demasiado": 1.6, "totalmente": 1.6,
    "completamente": 1.6, "absolutamente": 1.7, "realmente": 1.4,
    "bastante": 1.25, "un montón": 1.6, "montón": 1.5, "mucho": 1.4,
    "muchisimo": 1.7, "muchísimo": 1.7, "full": 1.5, "mil": 1.5,
}
ATENUADORES = {"medio": 0.6, "algo": 0.6, "un poco": 0.6, "poco": 0.6,
               "casi": 0.7, "apenas": 0.6, "más o menos": 0.5, "mas o menos": 0.5}

# ── "para nada" invierte: "para nada bueno" = malo
INVERSORES_FRASE = ["para nada", "ni ahí", "ni ahi", "nada que ver", "ni por asomo"]

# ── Marcadores de ironía. Solos no dicen nada: pesan al COMBINARSE con otra señal.
IRONIA = [
    r"\bsi+,?\s*claro\b", r"\bsí+,?\s*claro\b", r"\bobvio\b.*\bno\b",
    r"\bja+ja+\b", r"\bjaj+a+\b", r"\bes\s+joda\b", r"\bes\s+un\s+chiste\b",
    r"\bre+\s*tranquil", r"\bqu[eé]\s+lindo\b.*\bpero\b", r"\btodo\s+muy\s+lindo\b.*\bpero\b",
    r"\bgracias\b.*\bpero\b", r"\bexcelente\b.*\bpero\b", r"\bbarbaro\b.*\bpero\b",
    r"\bclaro\b.*\bmientras\b", r"\bseguro\b\.{2,}",
]

# ── Palabras que delatan una queja aunque no tengan polaridad léxica
PATRONES_QUEJA = [
    (r"\bhace\s+\d+\s*(dias?|días?|meses?|años?|semanas?)\b", -0.55,
     "reclamo con tiempo transcurrido"),
    (r"\b\d+\s*(dias?|días?|meses?)\s+(sin|esperando|y nada)\b", -0.7, "espera prolongada"),
    (r"\bme\s+(dejaron|dejan)\s+sin\b", -0.75, "privación"),
    (r"\btodav[ií]a\s+(espero|estoy esperando|no)\b", -0.65, "espera no resuelta"),
    (r"\bsigo\s+esperando\b", -0.7, "espera no resuelta"),
    (r"\bno\s+me\s+(pagan|pagaron|respondieron|atendieron|solucionaron)\b", -0.8,
     "incumplimiento"),
    (r"\bnunca\s+m[aá]s\b", -0.7, "ruptura"),
    (r"\bnadie\s+(me\s+)?(atiende|responde|contesta)\b", -0.8, "abandono"),
]

TOKEN_RE = re.compile(r"[a-záéíóúñü]+", re.I)


def _norm(t):
    """Baja a minúsculas y saca tildes SOLO para comparar (el lexicón trae ambas)."""
    return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                   if unicodedata.category(c) != "Mn")


def analizar(texto):
    """Devuelve Resultado(sentimiento, score, evidencia, ironia).

    score va de -1 a +1. La evidencia lista qué disparó cada aporte: es lo que hace
    al análisis defendible frente a alguien que pregunte "¿por qué dice negativo?".
    """
    if not texto or not texto.strip():
        return Resultado("neutro", 0.0, [], False)

    t = texto.lower()
    tn = _norm(t)
    evidencia, aportes = [], []

    # ── 1. Frases de varias palabras (van primero: "de cuarta" antes que "cuarta")
    for frase, peso in LEXICON.items():
        if " " in frase and _norm(frase) in tn:
            aportes.append(peso)
            evidencia.append((frase, peso, "expresión"))

    # ── 2. Patrones de queja (capturan quejas sin palabras negativas)
    for pat, peso, etiqueta in PATRONES_QUEJA:
        if re.search(pat, tn):
            aportes.append(peso)
            evidencia.append((etiqueta, peso, "patrón"))

    # ── 3. Palabra por palabra, con negación e intensificación
    palabras = TOKEN_RE.findall(t)
    palabras_n = [_norm(p) for p in palabras]

    negadores_n = {_norm(x) for x in NEGADORES}
    for i, p in enumerate(palabras_n):
        peso = LEXICON.get(p)
        if peso is None:
            peso = LEXICON.get(palabras[i])   # por si el lexicón lo tiene con tilde
        if peso is None:
            continue

        # ¿Hay un inversor de frase ("para nada", "ni ahí") justo antes?
        # Se chequea PRIMERO y corta: "para nada" contiene "nada", que también es
        # negador — si se contaran las dos cosas, la palabra se invertiría dos veces
        # y volvería a su signo original ("para nada bueno" daría positivo).
        contexto = " ".join(palabras_n[max(0, i - 3):i])
        inversor = next((inv for inv in INVERSORES_FRASE if _norm(inv) in contexto), None)

        ventana = palabras_n[max(0, i - ALCANCE_NEG):i]
        negs = 0 if inversor else sum(1 for w in ventana if w in negadores_n)

        nota = ""
        if inversor:
            peso = -peso
            nota = "invertido por '%s'" % inversor
        elif negs == 1:
            # Negación simple: invierte, pero amortiguada.
            # "no bueno" no es tan malo como "pésimo".
            peso = -peso * 0.75
            nota = "negado → invertido"
        elif negs >= 2:
            # DOBLE NEGACIÓN. Acá está la sutileza del español:
            #  · Si la palabra es NEGATIVA ("no está nada MAL"), las dos negaciones
            #    la invierten a positivo.
            #  · Si la palabra ya es NEGATIVA por concordancia ("NO me pagaron NUNCA"),
            #    no se cancelan: refuerzan. Se distingue por si el negador extra es
            #    'nunca/nadie/nada/jamás' actuando como concordancia negativa.
            concordancia = any(w in {"nunca", "jamas", "nadie", "ni", "tampoco"}
                               for w in ventana)
            if concordancia and peso < 0:
                peso = peso * 1.25          # refuerza la queja
                nota = "concordancia negativa → reforzado"
            else:
                peso = -peso * 0.85         # doble negación → se invierte
                nota = "doble negación → invertido"

        # Intensificadores / atenuadores inmediatamente previos
        if i > 0:
            prev = palabras_n[i - 1]
            bigrama = " ".join(palabras_n[max(0, i - 2):i])
            mult = None
            for k, v in INTENSIFICADORES.items():
                if _norm(k) == prev or _norm(k) == bigrama:
                    mult = v
                    break
            if mult is None:
                for k, v in ATENUADORES.items():
                    if _norm(k) == prev or _norm(k) == bigrama:
                        mult = v
                        break
            if mult:
                peso *= mult
                nota = (nota + " · " if nota else "") + ("intensificado ×%.1f" % mult)

        peso = max(-1.0, min(1.0, peso))
        aportes.append(peso)
        evidencia.append((palabras[i], round(peso, 2), nota or "léxico"))

    # ── 4. Emojis
    for e, peso in EMOJI.items():
        n = texto.count(e)
        if n:
            p = min(peso * (1 + 0.15 * (n - 1)), 1.0) if peso > 0 else \
                max(peso * (1 + 0.15 * (n - 1)), -1.0)
            aportes.append(p)
            evidencia.append((e, round(p, 2), "emoji ×%d" % n))

    # ── 5. Ironía.
    ironia = any(re.search(p, tn) for p in IRONIA)

    # La regla más potente, y la que un lexicón genérico nunca tiene:
    # un elogio conviviendo con una QUEJA CONCRETA es sarcasmo, casi sin excepción.
    #   "excelente, solo 3 meses para pagarme"  → el 'excelente' es irónico
    #   "muy tranquilo, hace 100 días que espero"
    # No alcanza con que haya un negativo cualquiera (un comentario puede decir
    # "buenos pero caros", que es matiz, no ironía). Tiene que haber un PATRÓN de queja
    # o una expresión temporal de reclamo.
    hay_elogio = any(p > 0.5 for p in aportes)
    hay_queja_concreta = (
        any(et == "patrón" for _, _, et in evidencia)
        or re.search(r"\b(solo|apenas|nada m[aá]s)\s+\d+\s*(d[ií]as?|meses?|a[ñn]os?|horas?)", tn)
        or re.search(r"\bhace\s+\d+\s*(d[ií]as?|meses?|a[ñn]os?)", tn)
    )
    if hay_elogio and hay_queja_concreta:
        ironia = True
        evidencia.append(("(elogio + queja concreta)", -1.0, "sarcasmo"))
    if ironia and aportes and sum(aportes) > 0:
        # No invierte a ciegas: amortigua fuerte y lo marca para revisión humana.
        aportes = [a * -0.5 if a > 0 else a for a in aportes]
        evidencia.append(("(ironía detectada)", -0.5, "positivos amortiguados"))

    if not aportes:
        return Resultado("neutro", 0.0, [], ironia)

    # Score: promedio con más peso al término más fuerte (una puteada define el tono).
    fuerte = max(aportes, key=abs)
    score = (sum(aportes) / len(aportes)) * 0.5 + fuerte * 0.5
    score = max(-1.0, min(1.0, score))

    if score >= 0.20:
        s = "positivo"
    elif score <= -0.20:
        s = "negativo"
    else:
        s = "neutro"
    return Resultado(s, round(score, 3), evidencia, ironia)


# ══════════════════════════════════════════════════════════ autotest

CASOS = [
    # (texto, esperado)  — los casos que rompen a un lexicón genérico
    ("no está nada mal el servicio", "positivo"),          # doble negación
    ("no me pagaron nunca el siniestro", "negativo"),      # concordancia negativa
    ("excelente, solo 3 meses para pagarme", "negativo"),  # ironía
    ("son unos chantas y cagadores", "negativo"),          # jerga uy
    ("bárbaro el servicio, de diez", "positivo"),          # jerga uy
    ("para nada bueno", "negativo"),                       # inversor de frase
    ("re buenos los muchachos", "positivo"),               # intensificador local
    ("me dejaron sin auto 6 meses", "negativo"),           # patrón sin palabra negativa
    ("gracias por todo, impecables", "positivo"),
    ("¿cubre granizo?", "neutro"),                         # pregunta
    ("todavía espero que me paguen", "negativo"),
    ("muy mala atención", "negativo"),
    ("nadie responde el teléfono", "negativo"),
]


def autotest(verbose=True):
    ok = 0
    for texto, esperado in CASOS:
        r = analizar(texto)
        bien = r.sentimiento == esperado
        ok += bien
        if verbose:
            print("  %s  %-42s → %-8s (%.2f)%s"
                  % ("✓" if bien else "✗", texto[:42], r.sentimiento, r.score,
                     "" if bien else "  ESPERADO: " + esperado))
            if not bien:
                print("       evidencia:", r.evidencia)
    print("\n  %d/%d casos correctos (%.0f%%)" % (ok, len(CASOS), ok / len(CASOS) * 100))
    return ok == len(CASOS)


if __name__ == "__main__":
    print("Autotest de lexico_uy — los casos que rompen a un lexicón genérico:\n")
    autotest()
