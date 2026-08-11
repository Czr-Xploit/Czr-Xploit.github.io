---
name: OWASP Amass
slug: amass
url: https://github.com/owasp-amass/amass
category: recon
tags: [recon, dns, superficie]
license: Apache-2.0
language: Go
featured: true
summary_es: >
  Mapeo de superficie externa por DNS. Lo elijo sobre las alternativas porque correlaciona
  fuentes pasivas y activas en un solo grafo consultable, en lugar de escupir una lista
  plana que luego tienes que deduplicar a mano.
summary_en: >
  External attack-surface mapping over DNS. I pick it over the alternatives because it
  correlates passive and active sources into one queryable graph instead of dumping a
  flat list you then have to deduplicate by hand.
---

<!-- es -->
El valor real no es que encuentre subdominios: eso lo hace cualquiera. Es que mantiene la
**procedencia** de cada hallazgo, así que puedes distinguir lo que salió de un registro
público de lo que salió de una resolución activa. Esa distinción importa cuando tienes
que justificar en un informe por qué tocaste algo.

Empieza siempre en modo pasivo. El modo activo genera tráfico atribuible y solo tiene
sentido dentro de un alcance autorizado por escrito.

<!-- en -->
The real value is not that it finds subdomains — anything does that. It is that it keeps
the **provenance** of each finding, so you can tell what came from a public record from
what came from active resolution. That distinction matters when you have to justify in a
report why you touched something.

Always start in passive mode. Active mode generates attributable traffic and only makes
sense inside a scope authorised in writing.
