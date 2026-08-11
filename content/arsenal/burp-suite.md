---
name: Burp Suite
slug: burp-suite
url: https://portswigger.net/burp
category: web
tags: [web, proxy, http]
license: Propietario (edición Community gratuita)
language: Java
featured: true
summary_es: >
  El proxy de interceptación de referencia para trabajo web. No lo elijo por las
  funciones automáticas, sino porque el historial de peticiones más Repeater cubre el 90%
  del trabajo real, y ese 90% funciona igual en la edición gratuita.
summary_en: >
  The reference intercepting proxy for web work. I do not pick it for the automated
  features but because the request history plus Repeater covers 90% of the real work, and
  that 90% behaves identically in the free edition.
---

<!-- es -->
Consejo poco popular: si estás aprendiendo, desactiva el escáner. La tentación de darle
al botón y leer el informe te salta la parte que enseña, que es mirar peticiones a mano
hasta que empiezas a notar lo que se sale del patrón.

Lo que sí automatizo desde el primer día es el **ámbito**. Un Burp sin ámbito
configurado acaba interceptando tráfico de sistemas que no estás autorizado a tocar, y
eso es un problema serio, no una molestia.

<!-- en -->
Unpopular advice: if you are learning, turn the scanner off. The temptation to hit the
button and read the report skips the part that teaches you anything, which is reading
requests by hand until you start noticing what breaks the pattern.

What I do automate from day one is **scope**. A Burp with no scope configured ends up
intercepting traffic from systems you are not authorised to touch, and that is a serious
problem rather than an inconvenience.
