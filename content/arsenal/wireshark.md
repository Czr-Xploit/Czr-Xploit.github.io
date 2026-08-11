---
name: Wireshark
slug: wireshark
url: https://www.wireshark.org/
category: network
tags: [red, protocolos, analisis]
license: GPL-2.0
language: C
featured: false
summary_es: >
  Análisis de protocolos paquete a paquete. Sigue siendo insustituible por una razón que
  no tiene que ver con la captura: sus disectores son la documentación más honesta que
  existe de cómo se ven de verdad los protocolos frente a cómo los describe el RFC.
summary_en: >
  Packet-by-packet protocol analysis. It stays irreplaceable for a reason that has
  nothing to do with capture: its dissectors are the most honest documentation there is
  of how protocols actually look versus how the RFC describes them.
---

<!-- es -->
Para trabajo en consola uso `tshark`, del mismo proyecto: mismos disectores, salida
canalizable. La interfaz gráfica la reservo para cuando necesito seguir un flujo y ver
la conversación completa reensamblada.

Un detalle de operación: las capturas contienen todo lo que pasó por el cable,
credenciales incluidas. Trátalas como material sensible desde el momento en que las
guardas, no cuando decides compartirlas.

<!-- en -->
For console work I use `tshark`, from the same project: same dissectors, pipeable output.
I keep the GUI for when I need to follow a stream and see the whole conversation
reassembled.

An operational note: captures contain everything that crossed the wire, credentials
included. Treat them as sensitive material from the moment you save them, not from the
moment you decide to share them.
