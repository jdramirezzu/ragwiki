# wikinotes

**La forma de tomar apuntes, evolucionada.** Entrega a wikinotes tu material de estudio y un
modelo de lenguaje construye y mantiene una wiki personal: páginas de Markdown enlazadas
entre sí que puedes leer, consultar y seguir ampliando. Cada afirmación enlaza al párrafo
del que salió.

[Read in English](README.md)

> Estado: desarrollo inicial. Los comandos se están construyendo de forma abierta; la
> [hoja de ruta](#hoja-de-ruta) indica qué funciona hoy.

## Inicio rápido

wikinotes todavía no está en PyPI. Se instala desde un clon con
[uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/jdramirezzu/wikinotes.git && cd wikinotes
uv sync
```

1. Indica qué modelo usar. Sirve cualquier servicio compatible con OpenAI:

   ```bash
   export WIKINOTES_MODEL="<nombre-del-modelo>"
   export WIKINOTES_BASE_URL="<url-del-proveedor>"   # Ollama local: http://localhost:11434/v1
   export WIKINOTES_API_KEY="<tu-clave>"             # no hace falta con un modelo local
   ```

2. Crea una carpeta y agrega tus notas:

   ```bash
   uv run wikinotes init mi-wiki
   cd mi-wiki
   uv run wikinotes add ~/notas/biologia.md
   uv run wikinotes status
   ```

3. Haz una pregunta. La respuesta cita los párrafos de donde sale, y avisa cuando tus notas
   no la cubren:

   ```bash
   uv run wikinotes ask "¿Qué hacen las mitocondrias?"
   ```

4. Abre `mi-wiki/` en Obsidian o en cualquier editor y lee tus páginas.

| Variable opcional | Significado |
|---|---|
| `WIKINOTES_PRICE_INPUT`, `WIKINOTES_PRICE_OUTPUT` | Precio de tu proveedor en USD por millón de tokens, para reportar el costo |
| `WIKINOTES_MAX_USD` | Tope de gasto de un comando |
| `WIKINOTES_VAULT` | Carpeta de la wiki, cuando no estás dentro de ella |
| `WIKINOTES_VISION_MODEL` | Modelo para las fotos, cuando el principal no ve imágenes |
| `WIKINOTES_VISION_BASE_URL`, `WIKINOTES_VISION_API_KEY` | Solo si el modelo de visión está en otro proveedor |
| `WIKINOTES_CONTEXT_TOKENS` | Ventana de contexto de tu modelo en tokens (32000 por defecto). Bájala para modelos locales pequeños |

Hoy wikinotes lee Markdown y texto (`.md`, `.markdown`, `.txt`), PDF, Word (`.docx`),
PowerPoint (`.pptx`), Excel (`.xlsx`) y fotos de apuntes (`.png`, `.jpg`, `.jpeg`, `.webp`).

Una foto la transcribe un modelo que pueda ver imágenes. La transcripción se guarda en
`extracted/` junto a tu foto original, para que puedas revisarla. Si tu modelo de texto no
ve imágenes, define `WIKINOTES_VISION_MODEL` con uno que sí. Un PDF necesita una capa de
texto: si es un escaneo, agrega sus páginas como fotos.

Antes de llamar al modelo, `add` muestra una estimación de llamadas, tokens y precio.
Cuando el precio es mayor que cero te pide confirmar; `--yes` omite la pregunta y
`--estimate` solo muestra la estimación. La estimación es aproximada: los tokens se
calculan a partir del largo del texto, y el costo real de cada llamada queda registrado en
`.wikinotes/calls.jsonl`.

Una fuente más grande que la ventana de contexto del modelo se divide en partes, y no se
escribe nada a menos que todas las partes salgan bien. Los párrafos nunca se cortan, así
que las citas siguen siendo exactas.

## Por qué una wiki y no solo búsqueda

La mayoría de las herramientas para "conversar con tus documentos" vuelven a buscar en tus
archivos con cada pregunta. wikinotes escribe el conocimiento una sola vez, en páginas que
conectan ideas entre tus fuentes, y las mantiene al día cuando agregas material.

El diseño nace de un proyecto de investigación de maestría que comparó los dos enfoques con
el mismo modelo y los mismos documentos:

| Hallazgo | Qué hace wikinotes |
|---|---|
| La wiki respondió bien más preguntas (0.78 frente a 0.54), y muchas más cuando la respuesta necesitaba varias fuentes (1.00 frente a 0.42) | La wiki es el centro del producto |
| Para un dato puntual de una sola fuente quedaron casi iguales, y la búsqueda costó cerca de una décima parte | La búsqueda sobre el texto original es el respaldo para datos precisos |
| La wiki a veces respondió cuando debía decir "no está en tus notas" y conservó valores desactualizados | Abstención explícita, citas verificadas por código y un comando `lint` |

Esas cifras salen de un experimento con 50 artículos científicos. Motivaron el diseño; no
son una garantía para tus apuntes.

## Cómo funciona

```
mi-wiki/
  sources/      tus archivos originales, nunca se modifican
  extracted/    cada fuente en Markdown con párrafos numerados
  wiki/         las páginas que escribe el modelo, enlazadas con [[enlaces]]
  index.md      catálogo de páginas
  log.md        historial de lo que se agregó
  SCHEMA.md     tus convenciones: tipos de página, idioma, estilo
```

La carpeta es Markdown plano. Ábrela en [Obsidian](https://obsidian.md) o en cualquier
editor: los enlaces y el grafo funcionan, y una cita te lleva al párrafo exacto de la fuente.

## Principios

- **Tu conocimiento es tuyo.** Archivos planos en tu disco, bajo Git, sin dependencia de un
  proveedor.
- **Cualquier modelo.** Funciona con cualquier servicio compatible con OpenAI, incluidos los
  modelos locales.
- **Trazable.** Una cita que no resuelve a un párrafo real se elimina.
- **Honesto.** Si tus notas no responden una pregunta, wikinotes lo dice.
- **Costos a la vista.** Cada llamada al modelo registra tokens, tiempo y precio, con un tope
  de gasto.

## Hoja de ruta

| Entrega | Alcance | Estado |
|---|---|---|
| M0 | Repositorio, empaquetado, CI | Hecho |
| M1 | Carpeta, ingesta de Markdown, preguntas con citas verificadas | Hecho |
| M2 | PDF, archivos de ofimática, fotos de apuntes a mano, fuentes largas, estimación de costo | Hecho |
| M3 | Respaldo de búsqueda en el texto original, `lint`, guardar respuestas como páginas | Planeado |
| Después | Interfaz gráfica, tarjetas de estudio, wikis compartidas | Se reciben ideas |

## Contribuir

Toda contribución es bienvenida. Empieza por [CONTRIBUTING.md](CONTRIBUTING.md).

## Licencia

[MIT](LICENSE)
