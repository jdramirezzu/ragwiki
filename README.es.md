# wikinotes

**La forma de tomar apuntes, evolucionada.** Entrega a wikinotes tu material de estudio y un
modelo de lenguaje construye y mantiene una wiki personal: páginas de Markdown enlazadas
entre sí que puedes leer, consultar y seguir ampliando. Cada afirmación enlaza al párrafo
del que salió.

[Read in English](README.md)

> Estado: desarrollo inicial. Los comandos se están construyendo de forma abierta; la
> [hoja de ruta](#hoja-de-ruta) indica qué funciona hoy.

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
| M1 | Carpeta, ingesta de Markdown, preguntas con citas verificadas | En curso |
| M2 | PDF, archivos de ofimática, fotos de apuntes a mano | Planeado |
| M3 | Respaldo de búsqueda en el texto original, `lint`, guardar respuestas como páginas | Planeado |
| Después | Interfaz gráfica, tarjetas de estudio, wikis compartidas | Se reciben ideas |

## Contribuir

Toda contribución es bienvenida. Empieza por [CONTRIBUTING.md](CONTRIBUTING.md).

## Licencia

[MIT](LICENSE)
