# CzrXplo1t.github.io

Blog bilingüe (ES/EN) de investigación en seguridad, con un generador estático propio
escrito en **Python puro, sin una sola dependencia de terceros**.

```
python3 build.py --serve
```

Eso es todo lo que hace falta para verlo funcionando. No hay `npm install`, no hay
`pip install`, no hay paso de compilación externo.

---

## Por qué cero dependencias

No es purismo. Para un blog de seguridad, la cadena de publicación es parte de la
superficie de ataque:

- **Cero supply chain.** No hay cuatrocientos paquetes transitivos entre lo que escribes y
  lo que se publica. El generador entero está en `tools/ssg/` y se puede leer en una tarde.
- **Cero terceros en el navegador.** Sin CDN, sin tipografías remotas, sin analítica, sin
  rastreadores. Cada byte que carga el visitante sale de tu propio origen.
- **CSP estricta.** `default-src 'none'`, `script-src 'self'`, sin `unsafe-inline` para
  scripts. La política se verifica en cada build.
- **Funciona sin JavaScript.** Todo lo interactivo es progresivo. Con JS desactivado el
  sitio se lee y se navega entero.
- **Build reproducible.** Dos builds del mismo commit producen bytes idénticos, y el CI lo
  comprueba.

---

## Requisitos

Python 3.11 o superior. Nada más.

```bash
python3 --version   # >= 3.11
```

---

## Uso

| Comando | Qué hace |
|---|---|
| `python3 build.py` | Genera el sitio en `dist/` |
| `python3 build.py --serve` | Genera y sirve en `http://127.0.0.1:8000` con rebuild al navegar |
| `python3 build.py --check` | Genera y ejecuta la verificación completa |
| `python3 build.py --check --strict` | Igual, pero sale con código ≠ 0 si hay cualquier hallazgo |
| `python3 build.py --drafts` | Incluye documentos con `draft: true` |
| `python3 build.py --no-minify` | Deja el CSS legible para depurar |
| `python3 build.py --clean` | Borra `dist/` |
| `python3 -m unittest discover -s tests` | Ejecuta la suite de tests |
| `python3 scripts/make-icons.py` | Regenera los iconos PWA desde código |

El servidor de desarrollo envía las mismas cabeceras de seguridad que declara la CSP, así
que una violación de política aparece en local y no después de desplegar.

---

## Estructura

```
build.py                  Punto de entrada
site.json                 Configuración del sitio
tools/ssg/                El generador (12 módulos, solo stdlib)
  markdown.py               Parser Markdown + contenedores propios
  highlight.py              Resaltado de sintaxis, 28 lenguajes
  sanitize.py               Sanitizador HTML por lista blanca
  template.py               Motor de plantillas (sin eval, sin llamadas)
  content.py                Frontmatter, modelo de documento, biblioteca
  builder.py                Orquestación del build
  check.py                  Verificación post-build
  ...
theme/
  templates/                Plantillas de página
  partials/                 Cabecera, pie, tarjeta, paleta, terminal
  css/                      Fuentes CSS (se concatenan en un bundle)
  static/                   Assets servidos tal cual (JS, imágenes, media)
content/
  posts/{es,en}/            Artículos de investigación
  writeups/{es,en}/         Writeups de laboratorio
  arsenal/                  Herramientas y recursos (bilingüe por campo)
  pages/{es,en}/            Páginas estáticas
tests/                     94 tests (markdown, seguridad, build, determinismo)
.claude/agents/            Tres agentes especializados del proyecto
```

---

## Escribir contenido

Un artículo es un fichero Markdown con frontmatter. El idioma se determina por el
directorio y **debe coincidir** con el campo `lang`.

```markdown
---
title: "Título del artículo"
slug: titulo-del-articulo
lang: es
translation_key: shared-key-between-languages
type: research
date: 2026-08-11
summary: >
  Una o dos frases. Aparece en los listados, en el feed y en la tarjeta social.
tags: [web, defensa]
toc: true
---

Contenido en Markdown.
```

`translation_key` empareja las versiones ES y EN. Debe aparecer exactamente dos veces en
todo `content/` — una por idioma. La verificación lo comprueba.

### Extensiones de Markdown disponibles

Además de Markdown estándar y las extensiones de GitHub (tablas, listas de tareas,
tachado, notas al pie):

````markdown
```python title="ejemplo.py" highlight="2,5-7" numbers
código con título, líneas resaltadas y numeración
```

++Ctrl+K++          teclas
==resaltado==       marca

::: note title="Opcional"
Aviso. Variantes: note, tip, warning, danger, success, info, quote
:::

::: terminal title="czr@lab"
czr@lab:~$ id
uid=1000(czr)
:::

::: spoiler title="Ver solución"
Contenido plegado.
:::

::: timeline title="Cronología"
- Día 0 — contacto
- Día 90 — publicación
:::

::: gif src="/static/media/gif/x.gif" poster="/static/img/x.png" alt="..."
Pie de figura. Se reproduce al hacer clic, nunca en automático.
:::

::: references
- [Fuente](https://ejemplo.tld)
:::
````

---

## Despliegue en GitHub Pages

1. Crea el repositorio **`CzrXplo1t.github.io`** en tu cuenta.
2. Sube este directorio:

   ```bash
   git add -A
   git commit -m "Sitio inicial"
   git branch -M main
   git remote add origin git@github.com:CzrXplo1t/CzrXplo1t.github.io.git
   git push -u origin main
   ```

3. En **Settings → Pages**, pon *Source* en **GitHub Actions**.
4. El workflow `.github/workflows/deploy.yml` construye, verifica, pasa los tests y publica.

`verify.yml` corre en cada rama y pull request: build, verificación estricta, tests en
Python 3.11/3.12/3.13, y comprobación de que el build es reproducible.

### Antes de confiar en el CI: fija las acciones

Los workflows referencian las acciones por etiqueta (`@v4`), que es **mutable**. Como el
job de despliegue tiene permisos `pages: write` e `id-token: write`, conviene fijarlas al
commit:

```bash
./scripts/pin-actions.sh --dry-run   # ver qué cambiaría
./scripts/pin-actions.sh             # reescribir con SHAs
```

---

## Verificación

`python3 build.py --check` ejecuta comprobaciones deterministas sobre el sitio generado:

- Ningún subrecurso de otro origen (CDN, tipografías, scripts externos)
- El generador no importa nada fuera de la biblioteca estándar
- CSP presente en todas las páginas, sin `unsafe-inline` en `script-src`
- Ningún script en línea ni manejador `on*` en la salida
- Enlaces internos y anclas que resuelven
- Feeds y sitemap que parsean como XML válido
- Emparejamiento ES/EN de cada `translation_key`
- Presupuestos de peso por página
- Recursos que bloquean el renderizado
- Fuga de material sensible: claves, tokens, direcciones privadas, rutas personales

### Presupuestos

| Recurso | Actual | Límite |
|---|---|---|
| CSS (gzip) | 12,1 KB | 45 KB |
| JavaScript (gzip) | 45,1 KB | 60 KB |
| Media total | 34,5 KB | 25 MB |
| GIF individual | — | 2 MB |
| Tipografías | 0 B | 220 KB |

Se definen en `site.json` y el build falla con `--strict` si se exceden.

---

## Agentes del proyecto

Tres agentes especializados en `.claude/agents/`, invocables desde Claude Code:

| Agente | Para qué |
|---|---|
| **`research-forge`** | Convierte notas en bruto en artículos verificados y bilingües. Construye un registro de afirmaciones y no publica nada que no pueda trazar a evidencia real |
| **`site-sentinel`** | Auditoría previa al despliegue: cadena de suministro, CSP, XSS en DOM, rendimiento, accesibilidad, integridad bilingüe, fugas de datos |
| **`glitch-smith`** | Sistema visual e interactivo: temas, animaciones, matrix, paleta de comandos, terminal, presentación de medios — siempre contra los presupuestos |

Los tres reportan en español y están escritos para **no dar por bueno nada que no hayan
medido o verificado**.

---

## Personalización

En `site.json`:

- `title`, `handle`, `author`, `base_url`
- `tagline` y `description` por idioma
- `default_theme` y la lista `themes` (`phosphor`, `amber`, `ice`, `redteam`)
- `social`, `email`
- `budgets`

El tema se cambia en el sitio con el botón de la cabecera, o desde la terminal integrada
con `theme amber`.

---

## Pendiente de completar

Cosas que solo tú puedes rellenar:

- [ ] **Clave PGP.** Sube tu clave pública a `theme/static/pgp/czrxplo1t.asc` y pon la ruta
      en `pgp_key_path` y la huella en `pgp_fingerprint` (`site.json`). Está vacío a
      propósito: un enlace a una clave inexistente es un enlace roto, y `--check` lo marca.
- [ ] **Correo de contacto.** Revisa `email` en `site.json`; alimenta `security.txt`.
- [ ] **Los marcadores `<!-- TODO CzrXplo1t -->`** en `whoami` y `contacto`.
- [ ] **Fijar las acciones del CI** con `./scripts/pin-actions.sh`.
- [ ] **Sustituir el contenido semilla.** Los artículos y writeups incluidos son reales y
      verificables, pero están ahí para ejercitar el renderizador. Bórralos cuando tengas
      los tuyos.

---

## Licencia

Código bajo MIT. Contenido bajo CC BY-NC-SA 4.0.
