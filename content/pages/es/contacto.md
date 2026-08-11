---
title: Contacto
slug: contacto
lang: es
translation_key: contact
type: page
date: 2026-01-15
summary: Cómo escribirme, cómo cifrar el mensaje y qué esperar como respuesta.
tags: [meta]
toc: false
---

## Canales

| Canal | Para qué | Tiempo de respuesta |
|:------|:---------|:--------------------|
| Correo | Todo lo demás | 3–7 días |
| `security.txt` | Reportar algo sobre **este** sitio | 72 h |
| GitHub | Erratas y correcciones al contenido | cuando lo vea |

La dirección de correo está en [`/.well-known/security.txt`](/.well-known/security.txt)
y en el pie de página. No la pongo en texto plano aquí por la razón evidente.

::: tip title="Antes de escribir"
Si tu mensaje es *«¿me enseñas a hackear?»*, la respuesta está en el
[Arsenal](/arsenal/): ahí está la lista de recursos con los que yo empecé, que es
exactamente lo que te contestaría.
:::

## PGP

Cifra cualquier cosa que contenga detalles de una vulnerabilidad no publicada, datos
de un cliente, o información que no querrías ver reenviada.

::: terminal title="czrxplo1t@lab"
czrxplo1t@lab:~$ curl -s https://CzrXplo1t.github.io/static/pgp/czrxplo1t.asc | gpg --import
gpg: key 0000000000000000: public key "CzrXplo1t" imported
gpg: Total number processed: 1
gpg:               imported: 1
czrxplo1t@lab:~$ gpg --fingerprint CzrXplo1t
:::

::: warning title="Verifica la huella"
Descargar una clave desde el mismo sitio que dice ser suyo no prueba nada por sí solo:
quien controle el sitio controla la clave. Contrasta la huella por un segundo canal
independiente antes de confiar en ella para algo serio.
:::

<!-- TODO CzrXplo1t: publicar la clave en theme/static/pgp/czrxplo1t.asc y poner la huella real en site.json -->

## Divulgación responsable

Si has encontrado algo en este sitio:

- [x] Escríbeme por `security.txt` con los pasos de reproducción.
- [x] Dame 72 horas para confirmar recepción.
- [ ] No hace falta que esperes 90 días: esto es un sitio estático personal, no un producto.

Te acreditaré por el nombre que me indiques, o no te acreditaré si prefieres eso.
Lo que no voy a hacer es publicar tu reporte sin avisarte.

## Lo que no hago

- No hago pruebas no autorizadas contra terceros, ni siquiera «para demostrar algo».
- No comparto material de clientes, ni anonimizado.
- No firmo acuerdos de confidencialidad para leer un reporte que quieres que revise gratis.
