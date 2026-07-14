# Monitor de categoría

Trae **un año de actividad real en redes** de una marca y sus competidores, y arma un tablero que
responde tres preguntas: **quién manda la conversación, de qué habla cada uno, y dónde nadie está.**

No es un contador de seguidores. Baja **cada posteo** de los últimos 12 meses vía [Apify](https://apify.com)
y calcula engagement real, cadencia, formatos, territorios de comunicación y evolución mes a mes.

Viene con una instancia lista: **seguros · Uruguay** (9 marcas). Para otra categoría se edita un
solo archivo — `monitor.config.json`.

<!-- Poné acá una captura del tablero: ayuda más que cualquier párrafo. -->

---

## Empezar

```bash
git clone https://github.com/Pedro1703/monitor-categoria.git
cd monitor-categoria
python3 app.py          # o doble clic en Abrir_Monitor.command
```

Se abre una app en tu navegador. Ahí:

1. **Pegás las credenciales una sola vez** (Apify, y Claude si querés sentimiento). Quedan
   guardadas en un `.env` local que **no se sube a GitHub**. No te las vuelve a pedir nunca.
2. **Elegís qué trackear**: las cuentas, las redes, el período, y si querés comentarios.
3. **Te dice cuánto va a costar** — antes de gastar un peso. Confirmás o cancelás.
4. Corre, y te deja **el tablero** y **el PPT en brand Ciudadana** listo para presentar.

Todo corre en tu máquina: los datos de la categoría nunca salen de tu compu.

### Desde la terminal, si preferís

```bash
python3 fetch_apify.py --dias 180     # baja posteos
python3 fetch_comments.py --estimar   # cuántos comentarios hay y cuánto salen (no gasta)
python3 fetch_comments.py             # los baja
python3 sentimiento.py --validar      # sentimiento + motivo, con validación
python3 analyze.py                    # métricas
python3 informe_ppt.py                # el PPT
```

El crudo queda cacheado en `raw/`. **Re-analizar no cuesta nada**: podés cambiar el lexicón o
rehacer el PPT sin volver a pagar scraping.

---

## Costo

Apify cobra por posteo scrapeado. Una corrida completa de 12 meses × 8 marcas ronda los
**1.000 posteos en Instagram y ~600 en Facebook**, o sea unos **US$ 4–8**.

Hay un techo duro: `limites.posts_por_marca_por_red` en la config (500 por defecto) hace que la
factura no se pueda disparar por accidente, publique lo que publique la competencia.

**Entra en el plan gratuito de Apify** (US$ 5 de crédito mensual) si corrés una vez por mes,
que es la cadencia recomendada — estas categorías se mueven lento.

La clasificación opcional con IA suma **US$ 1–2** por corrida.

---

## Qué mide, y por qué

| Métrica | Por qué está |
|---|---|
| **Share of engagement** | Qué porción de toda la interacción de la categoría se lleva cada marca. Más honesto que el share de posteos: **publicar mucho no es ser escuchado.** |
| **Tasa de engagement** | Engagement medio por posteo sobre seguidores. Compara marcas de distinto tamaño — es donde las chicas suelen ganarle a las grandes. |
| **Cadencia** | Posteos por semana. |
| **Territorios** | De qué habla la categoría y **qué porcentaje de cada territorio ocupa tu marca**. Un territorio donde estás en 0% es océano libre o flanco descubierto. Es la parte que se convierte en estrategia. |
| **Evolución mensual** | Tu marca contra el promedio de la competencia. |
| **Top posteos** | Los más potentes de la categoría, con link al original. |

Las alertas del tablero **no las escribe nadie**: salen de comparar los números de la ventana.

---

## Configurar otra categoría

Todo vive en `monitor.config.json`:

```jsonc
{
  "categoria": "Seguros · Uruguay",
  "ventana_dias": 365,
  "brands": [
    { "n": "BSE", "star": true, "ig": "bseuruguay", "fb": "BSEuruguay", "tt": null }
  ],
  "territorios": {
    "Institucional / país": ["orgullo", "uruguay", "país", "..."]
  }
}
```

- `star: true` marca al protagonista (el que va en aqua y contra el que se comparan todos).
- `ig` / `fb` / `tt` son los handles. `null` = esa marca no está en esa red.
- `territorios` es el lexicón de clasificación por reglas: palabra que aparece en el posteo → territorio.

Una marca sin ninguna red no es un error: el tablero la muestra como **ausencia deliberada**, que
suele ser un hallazgo (en seguros Uruguay, Zurich Santander no tiene cuenta propia).

---

## Cómo está armado

```
fetch_apify.py  →  raw/           →  analyze.py  →  monitor.data.js  →  index.html
(Apify)            (crudo cacheado)   (métricas)      (datos)             (tablero)
```

Tres piezas sueltas a propósito: si Apify cambia un actor, se toca solo la primera; si querés otra
métrica, solo la segunda; el tablero no sabe de dónde vinieron los datos.

- **`index.html`** — sin librerías externas, sin CDN, funciona offline y abre con doble clic.
- **La clasificación con IA es opcional y no crítica**: si falla (sin key, sin red), el monitor
  avisa y se queda con las reglas. **Nunca hay tablero vacío por un problema de la IA.**

---

## Los datos no están en este repo

El `.gitignore` excluye `raw/`, `monitor.json` y `monitor.data.js`. **Este repo es código, no data.**

Es a propósito: el tablero produce inteligencia competitiva, y esa no es información para dejar
indexada en un repo público. Cada quien corre el monitor con su token y sus datos se quedan en su
máquina. Tampoco hay tokens acá: `APIFY_TOKEN` y `ANTHROPIC_API_KEY` se leen del entorno.

---

## Sobre los gráficos

La marca protagonista va en un color; la competencia, en un único neutro. **La identidad la da
siempre la etiqueta, nunca el color** — así el tablero se lee igual con daltonismo, impreso en blanco
y negro, o proyectado en una sala con mal proyector. Las dos series están validadas por separación
de color y contraste.

---

## Licencia

MIT — ver [LICENSE](LICENSE).

Hecho para [CiudadanIA](https://github.com/Pedro1703) · Ciudadana.
