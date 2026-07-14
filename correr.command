#!/bin/bash
# Doble clic para actualizar el tablero.
cd "$(dirname "$0")"
if [ -z "$APIFY_TOKEN" ]; then
  echo "Pegá tu token de Apify (empieza con apify_api_) y dale Enter:"
  read -r APIFY_TOKEN
  export APIFY_TOKEN
fi
python3 fetch_apify.py && python3 analyze.py && open index.html
echo; echo "Listo. Cerrá esta ventana."
