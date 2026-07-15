# Guía de uso — Monitor de categoría

Guía básica para el equipo. No hace falta saber nada técnico: se usa desde una página web.

## Qué hace la herramienta

Analiza qué hacen una marca y su competencia en redes sociales:
- **Cuánto publican y cuánto engagement** generan (Instagram, Facebook, X/Twitter, TikTok).
- **De qué hablan** las marcas (territorios de comunicación).
- **Qué dice la gente** en los comentarios: sentimiento (positivo / neutro / negativo) y
  el **motivo** de cada comentario (por qué se queja o elogia: precio, atención, app, etc.).

El resultado es un **informe en PDF** con la marca de Ciudadana, listo para presentar.

## Cómo entrar

1. Abrí el link de la herramienta (el del deploy en Render).
2. Poné **tu nombre** y la **contraseña** del equipo.
3. Listo, entrás a la pantalla de armado.

## Paso a paso

### Paso 1 · Credenciales
Ya están cargadas (las claves de Apify y de Claude). **No toques nada** salvo que la
pantalla avise que falta alguna.

### Paso 2 · Qué querés trackear
- **País**: el país del análisis (ej. Uruguay, Argentina). Define la variante de español
  con la que se lee el sentimiento. Para Uruguay/Argentina el léxico está afinado; para
  otros países se usa como base y el informe lo aclara.
- **Redes a relevar**: elegí las que quieras (Instagram, Facebook, X, TikTok). **Solo se
  bajan comentarios de las redes que marques.**
- **Período**: último mes, 3 / 6 meses, un año, o personalizado.
- **Marcas**: agregá la **marca principal** (la del cliente) y sus competidores. En cada
  marca escribís su **usuario en cada red**. Marcá cuál es la principal con el botón
  **★ Principal**.
- **Comentarios del público**: dejá activados *"Bajar comentarios"* y *"Analizar el
  sentimiento"* si querés el análisis de opinión de la gente. (Sin esto, el informe trae
  solo la parte de publicaciones y engagement, y sale más barato.)

Cuando está todo, apretá **"Estimar el costo →"**.

### Paso 3 · Cuánto va a costar
Te muestra el costo estimado **sin gastar nada**, con el desglose por red.
- Si el volumen es alto y el costo **supera USD 100**, la herramienta te **ofrece tomar una
  muestra aleatoria** de comentarios (5 %, 10 %, 20 % o el valor que pongas) para gastar
  menos. Es opcional: por defecto procesa **todo**.

### Paso 4 · Ejecución
Si el costo te cierra, apretá **"Confirmar ejecución →"**. Vas a ver el progreso paso a paso
y el tiempo estimado. Cuando termina, aparece el botón **"Descargar el informe (PDF)"**.

## Repetir una consulta anterior

Cada corrida queda guardada. Con **"Repetir una consulta anterior ↺"** se rellenan todos los
campos de una corrida pasada: no hace falta recopiar marcas, redes ni país.

## Topes de gasto (para que nadie se pase)

- **Por corrida:** USD 25.
- **Por mes:** USD 100.
- Si una corrida supera el tope, se frena sola y te avisa.

## Si algo falla

- **"Sin créditos" (Apify o Claude):** hay que recargar saldo en esa cuenta. Después de
  recargar, usá el botón **"Reanudar desde donde quedó →"**: retoma sin volver a bajar (ni
  pagar) lo que ya estaba hecho.
- **La app tarda en abrir:** si estuvo un rato sin uso puede tardar unos segundos en
  despertar. Es normal.

## Cómo leer el informe (rápido)

- **Portada + metodología:** qué cuentas se analizaron, qué redes, y cómo (incluye el país,
  el motor de sentimiento y la validación cruzada).
- **Engagement y ranking:** quién se lleva la conversación de la categoría.
- **Territorios:** de qué temas habla cada marca y dónde hay espacio libre.
- **Sentimiento y motivos:** qué siente la gente y, sobre todo, **por qué** — que es lo que
  se convierte en decisión.

## Cómo funciona por dentro (resumen de una línea)

Baja datos públicos de redes con Apify, clasifica el sentimiento de los comentarios con
**RoBERTuito** (modelo gratuito de español) y el **motivo** con **Claude**, cruza todo con un
léxico rioplatense propio, y arma el PDF con diseño de Ciudadana. Detalle de los modelos en
`NLP_MODELOS.md`.
