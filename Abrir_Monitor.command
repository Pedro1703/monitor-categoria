#!/bin/bash
# Doble clic para abrir el Monitor de categoría.
cd "$(dirname "$0")"
python3 -c "import pptx, anthropic" 2>/dev/null || pip3 install -q python-pptx anthropic
python3 app.py
