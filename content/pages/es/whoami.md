---
title: whoami
slug: whoami
lang: es
translation_key: whoami
type: page
date: 2026-01-15
updated: 2026-08-11
summary: Quién está detrás de este sitio, qué se publica aquí y bajo qué reglas.
tags: [meta]
toc: true
---

## $ id

Soy **CzrXplo1t**. Trabajo en seguridad ofensiva: auditorías autorizadas, análisis de
vulnerabilidades e ingeniería inversa. Este sitio es el cuaderno donde acaban las cosas
que aprendo y que creo que le sirven a alguien más.

No es un portfolio ni un escaparate. Es un archivo técnico.

::: note title="Sobre los detalles personales"
Prefiero que el trabajo hable por sí solo, así que aquí no encontrarás mi nombre legal,
mi empleador ni una lista de certificaciones. Si necesitas verificar mi identidad para
un proceso formal, escríbeme firmado con PGP y lo resolvemos por canal privado.
:::

## $ cat ./que-se-publica

Tres cosas, y nada más:

1. **Research.** Análisis propios: cómo funciona algo por dentro, dónde se rompe y
   cómo detectarlo. Escrito para alguien que va a reproducirlo, no para alguien que
   va a citarlo en LinkedIn.
2. **Writeups.** Resoluciones de laboratorios y máquinas de entrenamiento. Incluyo los
   callejones sin salida, porque una lista de comandos ganadores no enseña nada.
3. **Arsenal.** Herramientas y recursos que uso de verdad, con la nota de por qué los
   elijo frente a la alternativa obvia.

Lo que **no** vas a encontrar: contenido patrocinado, resúmenes de noticias, listas de
«top 10 herramientas», ni nada generado sin que yo lo haya verificado.

## $ cat ./reglas-de-compromiso

Este es el punto que menos me gusta escribir y el más importante.

::: warning title="Uso autorizado únicamente"
Todo el material técnico de este sitio se publica con fines de investigación,
formación y defensa. Aplicar cualquiera de estas técnicas contra sistemas para los que
no tienes **autorización explícita y por escrito** es, en la mayoría de jurisdicciones,
un delito. La responsabilidad es enteramente de quien lo hace.
:::

Mis propias reglas, que aplico sin excepción:

- Todo lo que publico sobre un sistema de terceros ha pasado antes por un proceso de
  divulgación coordinada, o describe algo ya público.
- Los laboratorios y máquinas de entrenamiento son eso: entornos diseñados para ser
  atacados. Lo que hago ahí no se extrapola.
- Ninguna captura, transcripción o volcado sale de aquí sin pasar por redacción:
  hostnames internos, direcciones, tokens, datos de cliente y metadatos EXIF.
- Si un artículo explica un ataque, explica también cómo detectarlo y cómo mitigarlo.
  Si no puedo escribir la segunda mitad, no publico la primera.

## $ cat ./divulgacion

Sigo divulgación coordinada por defecto:

::: timeline title="Proceso estándar"
- Día 0 — Contacto con el responsable por su canal declarado (security.txt, programa de bug bounty, o el contacto público que exista).
- Día 0–7 — Confirmación de recepción. Si no la hay, segundo intento por vía alternativa.
- Día 7–90 — Ventana de corrección. Colaboro en la reproducción y la verificación del parche si hace falta.
- Día 90 — Publicación, coordinada con el responsable si sigue habiendo diálogo.
- Sin respuesta a los 90 días — Publicación, previo aviso de 14 días.
:::

Los plazos se negocian si hay motivo técnico real. No se negocian si el motivo es
que la publicación resulta incómoda.

## $ cat ./este-sitio

Está construido con un generador estático propio, escrito en Python, **sin una sola
dependencia de terceros**. La decisión no es estética:

- No hay `npm install` de cuatrocientos paquetes transitivos en la cadena de publicación.
- No hay CDN, ni tipografías remotas, ni analítica, ni rastreadores. Cada byte que
  carga tu navegador sale de este mismo origen.
- La política de seguridad de contenido es estricta y no admite scripts en línea.
- Funciona entero con JavaScript desactivado. Lo interactivo es un añadido, nunca un requisito.

::: tip title="Verificable"
Todo el código del sitio y del generador está publicado. Si algo de lo anterior no te
lo crees, es comprobable en dos minutos: mira el código fuente y la pestaña de red.
:::

## $ cat ./contacto

Escríbeme cifrado siempre que el contenido lo justifique. La clave pública y las
huellas están en la [página de contacto](/contacto/).

Para reportarme algo sobre este sitio en concreto, el canal formal está en
[`/.well-known/security.txt`](/.well-known/security.txt).

<!-- TODO CzrXplo1t: sustituir la huella PGP en site.json y subir la clave a theme/static/pgp/ -->
