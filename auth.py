#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autenticación y control de gasto.

POR QUÉ NO ALCANZA CON LA CONTRASEÑA
====================================
La app publicada guarda las keys de Apify y Anthropic. Cualquiera que entre puede
lanzar corridas que cuestan plata REAL — la de Pedro. La contraseña evita al extraño;
no evita el accidente: alguien deja una pestaña abierta, prueba diez veces, o mete
una ventana de 3 años sobre 20 marcas sin mirar el costo.

Por eso hay tres capas, no una:

  1. CONTRASEÑA        — cookie de sesión firmada. Nadie entra sin ella.
  2. TOPES DE GASTO    — por corrida y por mes. Si se pasa, NO corre. Es el freno
                          que convierte un error humano en un mensaje, no en una factura.
  3. REGISTRO          — cada corrida queda anotada: quién, cuándo, cuánto costó.
                          Si algo se dispara, se sabe de dónde vino.

Todo se configura por variable de entorno — nada de esto va en el código, porque el
repo es público y una contraseña commiteada no es una contraseña:
    JAVIA_PASSWORD       (obligatoria: sin ella la app no arranca)
    JAVIA_SECRET         (firma las cookies; si falta, se genera una por arranque)
    JAVIA_TOPE_CORRIDA   (default: 25 USD)
    JAVIA_TOPE_MES       (default: 100 USD)
"""

import os, sys, json, time, hmac, hashlib, base64, secrets

HERE = os.path.dirname(os.path.abspath(__file__))
BITACORA = os.path.join(HERE, "raw", "bitacora.json")

# Cargar el .env ANTES de leer la contraseña: si no, auth se importa antes que
# config_local.cargar() y la clave local no aparece.
sys.path.insert(0, HERE)
try:
    import config_local
    config_local.cargar()
except Exception:
    pass

# La contraseña NO va en el código: el repo es público y quedaría a la vista de
# cualquiera, lo que anula el sentido de tener contraseña. Se lee del entorno.
# Sin ella, la app no arranca — es preferible que falle a que quede abierta.
PASSWORD = os.environ.get("JAVIA_PASSWORD", "").strip()
TOPE_CORRIDA = float(os.environ.get("JAVIA_TOPE_CORRIDA", "25"))
TOPE_MES = float(os.environ.get("JAVIA_TOPE_MES", "100"))

# Secreto para firmar la cookie. Si no se define, se genera uno por arranque:
# eso invalida las sesiones al reiniciar, que es un default seguro.
SECRETO = os.environ.get("JAVIA_SECRET", secrets.token_hex(32)).encode()

DURACION = 12 * 3600      # la sesión dura 12 horas


def configurada():
    return bool(PASSWORD)


# ────────────────────────────────────────────────── sesión

def _firmar(dato):
    mac = hmac.new(SECRETO, dato.encode(), hashlib.sha256).hexdigest()[:32]
    return "%s.%s" % (dato, mac)


def crear_cookie(quien):
    """Cookie firmada: usuario + vencimiento. No se puede falsificar sin el secreto."""
    dato = base64.urlsafe_b64encode(
        json.dumps({"q": quien, "exp": int(time.time()) + DURACION}).encode()
    ).decode()
    return _firmar(dato)


def leer_cookie(valor):
    """Devuelve quién es, o None si la cookie es inválida o venció."""
    if not valor or "." not in valor:
        return None
    dato, mac = valor.rsplit(".", 1)
    esperado = hmac.new(SECRETO, dato.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(mac, esperado):     # comparación a tiempo constante
        return None
    try:
        d = json.loads(base64.urlsafe_b64decode(dato.encode()))
    except Exception:
        return None
    if d.get("exp", 0) < time.time():
        return None
    return d.get("q") or "equipo"


def verificar_password(intento):
    return hmac.compare_digest((intento or "").strip(), PASSWORD)


# ────────────────────────────────────────────────── gasto

def _bitacora():
    if not os.path.exists(BITACORA):
        return []
    try:
        return json.load(open(BITACORA, encoding="utf-8"))
    except Exception:
        return []


def registrar_corrida(quien, costo_est, detalle):
    """Anota quién lanzó qué. Sin esto, un gasto raro no tiene dueño."""
    b = _bitacora()
    b.append({
        "cuando": time.strftime("%Y-%m-%d %H:%M"),
        "mes": time.strftime("%Y-%m"),
        "quien": quien,
        "costo_estimado": round(costo_est, 2),
        "detalle": detalle,
    })
    os.makedirs(os.path.dirname(BITACORA), exist_ok=True)
    json.dump(b, open(BITACORA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def gastado_este_mes():
    mes = time.strftime("%Y-%m")
    return round(sum(c["costo_estimado"] for c in _bitacora() if c.get("mes") == mes), 2)


def puede_correr(costo_est):
    """¿Se autoriza esta corrida? Devuelve (sí/no, motivo).

    Se chequea sobre el costo ESTIMADO MÁXIMO, no el promedio: el freno tiene que
    frenar antes, no después de gastar.
    """
    if costo_est > TOPE_CORRIDA:
        return False, ("Esta corrida costaría hasta USD %.2f y el tope por corrida es "
                       "USD %.2f. Achicá el período, las marcas o las redes — o pedile a "
                       "Pedro que suba el tope." % (costo_est, TOPE_CORRIDA))
    mes = gastado_este_mes()
    if mes + costo_est > TOPE_MES:
        return False, ("Este mes ya se gastaron USD %.2f y esta corrida sumaría hasta "
                       "USD %.2f, pasando el tope mensual de USD %.2f. Contactá a Pedro."
                       % (mes, costo_est, TOPE_MES))
    return True, ""


def estado_gasto():
    return {
        "mes": gastado_este_mes(),
        "tope_mes": TOPE_MES,
        "tope_corrida": TOPE_CORRIDA,
        "corridas_mes": len([c for c in _bitacora() if c.get("mes") == time.strftime("%Y-%m")]),
    }
