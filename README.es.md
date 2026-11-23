# ragwiki

**¿Búsqueda vectorial o WikiLLM? Construye cualquiera de las dos con tus propios documentos y
deja que tus preguntas decidan.** ragwiki convierte archivos PDF, Word, PowerPoint y de texto
en un índice de búsqueda vectorial (RAG), en una wiki que un modelo de lenguaje escribe y
mantiene enlazada (WikiLLM), o en ambas, y responde con el mismo modelo en los dos casos.
Cada afirmación enlaza al párrafo del que salió.

[Read in English](README.md)

Mira la introducción de 90 segundos: [español](docs/video/media/ragwiki-intro-es.mp4) · [English](docs/video/media/ragwiki-intro-en.mp4). Se genera con código en [`docs/video`](docs/video/README.md).

> Estado: desarrollo inicial, construido de forma abierta a partir de un proyecto de
> investigación de maestría. La [hoja de ruta](#hoja-de-ruta) indica qué funciona hoy.

## Inicio rápido: el laboratorio

```bash
git clone https://github.com/jdramirezzu/ragwiki.git && cd ragwiki
uv sync --extra lab
uv run ragwiki lab ~/mi-laboratorio
```

La página se abre en tu navegador en `http://127.0.0.1:8765`. Corre solo en tu computador;
lo único que sale de él son las llamadas al modelo. Configura el modelo en la página (la
clave se guarda en memoria, nunca en disco) o con las variables `RAGWIKI_*` de más abajo.

1. **Archivos.** Arrastra PDF, archivos de Word o PowerPoint, o texto plano (`.txt`, `.md`).
   Agregarlos es gratis: el texto se extrae en tu computador en párrafos citables.
2. **Construir.** Construye el índice de **búsqueda vectorial** (embeddings en tu computador,
   gratis; o los de tu proveedor), la **WikiLLM** (unas dos llamadas al modelo por archivo,
   con el costo a la vista antes de gastar) o las dos. La página explica en qué se
   diferencian y cuándo conviene cada una.
3. **Preguntar.** Pregunta con la que construiste, o con las dos: el mismo modelo responde
   dos veces y las respuestas aparecen lado a lado con sus citas, tokens, tiempo y costo.
   Al hacer clic en una cita, el párrafo de la fuente aparece al lado. Si quieres, agrega la
   respuesta esperada como términos clave (`¿Qué produce ATP? | ATP, mitocondria`), o `none`
   cuando tus archivos no la responden.
4. **Resultados.** Juzga cada par, descarga todo en CSV o JSONL y lee la recomendación: la
   WikiLLM se sugiere solo cuando responde claramente mejor (una diferencia de al menos
   0,10 con cinco o más preguntas evaluadas); si no, la búsqueda vectorial, que cuesta menos.

| | Búsqueda vectorial (RAG) | WikiLLM |
|---|---|---|
| Cuándo se hace el trabajo | En cada pregunta | Una vez, al agregar un archivo |
| Construir | Gratis con embeddings locales | Unas 2 llamadas al modelo por archivo |
| Cada pregunta | 1 llamada al modelo | Hasta 8 llamadas al modelo |
| Mejor para | Datos puntuales; archivos que cambian seguido | Preguntas que unen varios documentos |
| Además obtienes | Nada para leer | Una wiki enlazada que puedes recorrer en Obsidian |

## Línea de comandos

ragwiki todavía no está en PyPI. Se instala desde un clon con
[uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/jdramirezzu/ragwiki.git && cd ragwiki
uv sync
```

1. Indica qué modelo usar. Sirve cualquier servicio compatible con OpenAI:

   ```bash
   export RAGWIKI_MODEL="<nombre-del-modelo>"
   export RAGWIKI_BASE_URL="<url-del-proveedor>"   # Ollama local: http://localhost:11434/v1
   export RAGWIKI_API_KEY="<tu-clave>"             # no hace falta con un modelo local
   ```

2. Crea una carpeta y agrega tus notas:

   ```bash
   uv run ragwiki init mi-wiki
   cd mi-wiki
   uv run ragwiki add ~/notas/biologia.md
   uv run ragwiki status
   ```

3. Haz una pregunta. La respuesta cita los párrafos de donde sale, y avisa cuando tus notas
   no la cubren:

   ```bash
   uv run ragwiki ask "¿Qué hacen las mitocondrias?"
   ```

4. Abre `mi-wiki/` en Obsidian o en cualquier editor y lee tus páginas.

¿No tienes apuntes a mano? Sigue el [paso a paso](docs/demo.md) (en inglés) con las notas de
ejemplo de [`examples/`](examples/README.md).

| Variable opcional | Significado |
|---|---|
| `RAGWIKI_PRICE_INPUT`, `RAGWIKI_PRICE_OUTPUT` | Precio de tu proveedor en USD por millón de tokens, para reportar el costo |
| `RAGWIKI_MAX_USD` | Tope de gasto de un comando |
| `RAGWIKI_VAULT` | Carpeta de la wiki, cuando no estás dentro de ella |
| `RAGWIKI_VISION_MODEL` | Modelo para las fotos, cuando el principal no ve imágenes |
| `RAGWIKI_VISION_BASE_URL`, `RAGWIKI_VISION_API_KEY` | Solo si el modelo de visión está en otro proveedor |
| `RAGWIKI_CONTEXT_TOKENS` | Ventana de contexto de tu modelo en tokens (32000 por defecto). Bájala para modelos locales pequeños |

Hoy ragwiki lee Markdown y texto (`.md`, `.markdown`, `.txt`), PDF, Word (`.docx`),
PowerPoint (`.pptx`) y fotos de apuntes (`.png`, `.jpg`, `.jpeg`, `.webp`). Las hojas de
cálculo quedan fuera a propósito: contienen datos, no apuntes.

Una foto la transcribe un modelo que pueda ver imágenes. La transcripción se guarda en
`extracted/` junto a tu foto original, para que puedas revisarla. Si tu modelo de texto no
ve imágenes, define `RAGWIKI_VISION_MODEL` con uno que sí. Un PDF necesita una capa de
texto: si es un escaneo, agrega sus páginas como fotos.

Antes de llamar al modelo, `add` muestra una estimación de llamadas, tokens y precio.
Cuando el precio es mayor que cero te pide confirmar; `--yes` omite la pregunta y
`--estimate` solo muestra la estimación. La estimación es aproximada: los tokens se
calculan a partir del largo del texto, y el costo real de cada llamada queda registrado en
`.ragwiki/calls.jsonl`.

Una fuente más grande que la ventana de contexto del modelo se divide en partes, y no se
escribe nada a menos que todas las partes salgan bien. Los párrafos nunca se cortan, así
que las citas siguen siendo exactas.

## Por qué una wiki y no solo búsqueda

La mayoría de las herramientas para "conversar con tus documentos" vuelven a buscar en tus
archivos con cada pregunta. ragwiki escribe el conocimiento una sola vez, en páginas que
conectan ideas entre tus fuentes, y las mantiene al día cuando agregas material.

El diseño nace de un [proyecto de investigación de maestría](https://github.com/1KVueltasAlCampo/llm-knowledge-management-wiki-agent) que comparó los
dos enfoques con el mismo modelo, los mismos 100 artículos científicos y las mismas 100
preguntas:

| Hallazgo | Qué hace ragwiki |
|---|---|
| La wiki respondió bien más preguntas (0,70 frente a 0,48 con 5 párrafos recuperados), y su ventaja fue mayor cuando la respuesta unía varios artículos | La wiki es el centro del producto |
| Cada pregunta a la wiki costó 7,2 veces más y tardó 4,1 veces más, además de un costo único para construirla. Con 20 párrafos para el RAG la ventaja bajó a +0,06, sin significancia | El [laboratorio](#inicio-rápido-el-laboratorio) te deja comprobar cuál conviene con tus archivos |
| La wiki conservó lo aprendido, pero captó del 63 % al 80 % de lo que podía y no retiró valores desactualizados | Abstención explícita, citas verificadas por código y un comando `lint` planeado |

Esas cifras salen de un experimento con artículos de arXiv. Motivaron el diseño; no son una
garantía para tus apuntes.

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
- **Honesto.** Si tus notas no responden una pregunta, ragwiki lo dice.
- **Costos a la vista.** Cada llamada al modelo registra tokens, tiempo y precio, con un tope
  de gasto.

## Hoja de ruta

| Entrega | Alcance | Estado |
|---|---|---|
| M0 | Repositorio, empaquetado, CI | Hecho |
| M1 | Carpeta, ingesta de Markdown, preguntas con citas verificadas | Hecho |
| M2 | PDF, archivos de ofimática, fotos de apuntes a mano, fuentes largas, estimación de costo | Hecho |
| Laboratorio | Construir búsqueda vectorial o una WikiLLM con tus archivos, preguntar con cualquiera, comparar ambas y recibir una recomendación | Hecho |
| M3 | Respaldo de búsqueda en el texto original, `lint`, guardar respuestas como páginas | Planeado |
| Después | Interfaz gráfica, tarjetas de estudio, wikis compartidas | Se reciben ideas |

## Contribuir

Toda contribución es bienvenida. Empieza por [CONTRIBUTING.md](CONTRIBUTING.md).

El laboratorio es la primera interfaz gráfica: un servidor pequeño en FastAPI (`server.py`)
y una página sin paso de compilación (`src/ragwiki/web/`). Si diseñas o construyes
interfaces, lee
[Designing an interface for ragwiki](docs/interface.md) (en inglés).

## Licencia

[MIT](LICENSE)
