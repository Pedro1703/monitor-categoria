# Qué modelos de NLP usa el monitor (y por qué)

Resumen para decidir: **el mejor modelo para español rioplatense hoy es un LLM (Claude),
y es el motor principal.** El mejor modelo *gratis y offline* es **RoBERTuito
(pysentimiento)**, que se suma como validación o como alternativa sin costo. El fallback
de cero dependencias es el **léxico rioplatense propio**. Los tres conviven.

## El problema específico: español "con peculiaridades de cada país"

El español no es uno. "Excelente, solo 3 meses para pagarme" es **negativo** (ironía), el
voseo rioplatense, los mexicanismos, el "che", el "bárbaro", el "de más"… Un modelo
entrenado con español formal (Wikipedia, boletines oficiales) se rompe con esto. Hacen
falta modelos entrenados con **lenguaje social real y de muchos países**.

## La arquitectura de tres capas

| Capa | Motor | Costo | Dónde corre | Rol |
|---|---|---|---|---|
| **Principal** | Claude Opus | Pago (~US$1,4/1.000 comentarios) | API | Clasifica sentimiento **+ motivo**. Razona la ironía y el voseo. |
| **Gratis / offline** | RoBERTuito (pysentimiento) | Gratis | Local o instancia paga | Tercer voto de validación, o motor sin costo cuando no hay presupuesto. |
| **Fallback cero-deps** | Léxico rioplatense (`lexico_uy.py`) | Gratis | Cualquier lado, incl. nube 512 MB | Cruce siempre disponible; atrapa lo que un léxico solo vería mal. |

Cuantos más métodos **independientes** coinciden en un comentario, más confiable el número.
Por eso el informe muestra el acuerdo entre capas, no un solo número a ciegas.

## Por qué Claude es el principal (no un capricho)

- Es el único que **razona** el sarcasmo en vez de sumar palabras. La ironía es donde
  mueren los léxicos y los modelos chicos.
- Devuelve **motivo** además de sentimiento (por qué se queja la gente), que es la parte
  accionable. Un modelo de sentimiento puro no hace esto.
- Hay investigación reciente de LLMs sobre **español rioplatense** (p. ej. detección de
  discurso de odio) que los ubica al frente para esta variante.

Contra: cuesta por token. Por eso las otras dos capas.

## Por qué RoBERTuito es el mejor gratis

`pysentimiento/robertuito-sentiment-analysis`:

- RoBERTa preentrenado con **~500 millones de tweets en español de muchos países** → esa
  base multi-país es lo que le da oído regional (rioplatense, mexicano, etc.).
- En los benchmarks de **TASS** supera a **BETO** y a **mBERT** en sentimiento
  (Macro-F1 ≈ 0,70).
- Mismo paquete hace sentimiento, emoción, ironía y discurso de odio.

Contra: **pesa**. `pip install pysentimiento` arrastra PyTorch (~1-2 GB) + pesos (~500 MB).
**No entra en el plan free de Render (512 MB de RAM).** Es para correr local o en instancia
paga. Está integrado como **opcional** (`nlp_local.py`): si no está instalado, el pipeline
sigue igual.

### Cómo activarlo

```bash
pip install pysentimiento
python3 nlp_local.py          # prueba rápida
```

Con eso, `reporte_sentimiento.py` suma automáticamente el "tercer voto" y muestra cuánto
coinciden los tres métodos.

## Alternativas que evalué y descarté (para este caso)

- **BETO** (dccuchile/bert-base-spanish): el primer BERT en español. Entrenado con
  Wikipedia/OPUS → **español general**, no social. Peor con jerga e ironía. RoBERTuito nace
  justamente para cubrir ese hueco.
- **XLM-T / XLM-RoBERTa**: multilingüe (30+ idiomas, Twitter). Útil si necesitás muchos
  idiomas; para español puntual, RoBERTuito es más fino.
- **MarIA / RoBERTa-large-bne** (Biblioteca Nacional de España): español **formal** (BOE).
  Excelente para texto legal, malo para comentarios de Instagram.
- **tabularisai/multilingual-sentiment** (2025): multilingüe general, buen demo, pero sin
  el foco social/dialectal de RoBERTuito.
- **VADER / TextBlob**: pensados para inglés. En español, y peor en rioplatense, no sirven.

## Recomendación final

1. **Dejar Claude como motor principal** — es lo mejor para esta variante y da el motivo.
2. **Instalar RoBERTuito donde se pueda** (local / instancia paga) para el tercer voto
   gratis. En la nube free, se omite solo.
3. **Mantener el léxico rioplatense** como red de seguridad de cero dependencias.

No hay un único "mejor modelo": hay una combinación. La calidad sale del **acuerdo entre
tres métodos independientes**, no de confiar a ciegas en uno.
