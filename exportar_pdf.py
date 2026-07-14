#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Exporta el informe a PDF. El PDF es la entrega; el PPT queda por si hay que editarlo.

Prueba tres caminos, en orden, y usa el primero que funcione:
  1. LibreOffice  — headless, sin abrir ninguna app. El más limpio si está instalado.
  2. PowerPoint   — vía AppleScript (Mac). Abre la app un segundo.
  3. Keynote      — último recurso.

Si ninguno está, avisa y deja el PPTX: la corrida no se cae por no poder hacer el PDF.

    python3 exportar_pdf.py
"""

import os, sys, subprocess, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PPTX = os.path.join(HERE, "Informe_Ciudadana.pptx")
PDF = os.path.join(HERE, "Informe_Ciudadana.pdf")


def por_libreoffice():
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice and os.path.exists("/Applications/LibreOffice.app"):
        soffice = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if not soffice:
        return False
    r = subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                        "--outdir", HERE, PPTX],
                       capture_output=True, timeout=240)
    return r.returncode == 0 and os.path.exists(PDF)


def _osascript(app, guardar):
    if not os.path.exists("/Applications/%s.app" % app):
        return False
    r = subprocess.run(["osascript", "-e", guardar], capture_output=True,
                       text=True, timeout=300)
    return r.returncode == 0 and os.path.exists(PDF)


def por_powerpoint():
    return _osascript("Microsoft PowerPoint", '''
tell application "Microsoft PowerPoint"
    activate
    open POSIX file "%s"
    set d to active presentation
    save d in POSIX file "%s" as save as PDF
    close d saving no
end tell''' % (PPTX, PDF))


def por_keynote():
    return _osascript("Keynote", '''
tell application "Keynote"
    activate
    set d to open POSIX file "%s"
    delay 2
    export d to POSIX file "%s" as PDF
    close d saving no
end tell''' % (PPTX, PDF))


def main():
    if not os.path.exists(PPTX):
        print("ERROR: no existe el PPT. Corré informe_ppt.py", file=sys.stderr)
        return 1
    if os.path.exists(PDF):
        os.remove(PDF)

    for nombre, fn in (("LibreOffice", por_libreoffice),
                       ("PowerPoint", por_powerpoint),
                       ("Keynote", por_keynote)):
        try:
            if fn():
                kb = os.path.getsize(PDF) // 1024
                print("OK · Informe_Ciudadana.pdf (%d KB, vía %s)" % (kb, nombre))
                return 0
        except Exception as e:
            print("  [aviso] %s no pudo: %s" % (nombre, e), file=sys.stderr)

    # No poder generar el PDF no invalida el trabajo: el PPT está.
    print("[aviso] No se pudo generar el PDF (no hay LibreOffice, PowerPoint ni Keynote).\n"
          "        El informe igual está en Informe_Ciudadana.pptx.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
