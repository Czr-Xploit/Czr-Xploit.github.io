---
name: Nmap
slug: nmap
url: https://nmap.org/
category: network
tags: [red, enumeracion, recon]
license: NPSL (derivada de GPL-2.0)
language: C
featured: false
summary_es: >
  Descubrimiento de hosts y servicios. Sigue siendo el primero que abro por una razón
  concreta: su detección de versiones y su motor de scripts convierten "hay algo
  escuchando en el 8080" en "esto es tal software, tal versión", que es la diferencia
  entre una lista de puertos y un inventario.
summary_en: >
  Host and service discovery. It is still the first thing I open for a specific reason:
  version detection plus the scripting engine turn "something is listening on 8080" into
  "this is that software, that version", which is the difference between a port list and
  an inventory.
---

<!-- es -->
Lee la salida completa, no solo la tabla de puertos. Los avisos que imprime sobre
respuestas raras, TTLs inconsistentes o fingerprints que no cuadran suelen ser la pista
más útil de la sesión, y casi todo el mundo los salta.

Sobre los scripts: la categoría `default` es segura para reconocimiento. Las categorías
`intrusive` y `exploit` hacen exactamente lo que su nombre indica — no las lances contra
un sistema en producción sin haberlo acordado por escrito.

<!-- en -->
Read the full output, not just the port table. The warnings it prints about odd
responses, inconsistent TTLs or fingerprints that do not add up are often the most useful
lead of the session, and almost everyone skips them.

On scripts: the `default` category is safe for reconnaissance. The `intrusive` and
`exploit` categories do exactly what their names say — do not run them against a
production system without having agreed it in writing.
