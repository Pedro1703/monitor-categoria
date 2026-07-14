FROM python:3.11-slim

# LibreOffice: es lo que exporta el informe a PDF en Linux (en Mac usa PowerPoint).
# Sin esto, el PDF no se genera y solo queda el PPTX.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Los datos (crudo, informes) viven en un volumen: sobreviven a los redeploys.
ENV JAVIA_PUERTO=8080
EXPOSE 8080
CMD ["python3", "app.py"]
