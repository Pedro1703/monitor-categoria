FROM python:3.11-slim

# LibreOffice: es lo que exporta el informe a PDF en Linux (en Mac usa PowerPoint).
# Sin esto, el PDF no se genera y solo queda el PPTX.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch en versión CPU (el índice normal trae CUDA, ~2 GB de más que no usamos).
# Va ANTES de requirements para que pysentimiento vea torch ya satisfecho y no lo repise.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cache de HuggingFace en el disco persistente (/app/raw está montado como volumen):
# los pesos de RoBERTuito (~500 MB) se bajan una vez y sobreviven a los redeploys.
ENV HF_HOME=/app/raw/hf
ENV JAVIA_PUERTO=8080
EXPOSE 8080
CMD ["python3", "app.py"]
