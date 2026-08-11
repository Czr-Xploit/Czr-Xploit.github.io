---
name: Ghidra
slug: ghidra
url: https://ghidra-sre.org/
category: reversing
tags: [reversing, binarios, desensamblado]
license: Apache-2.0
language: Java
featured: true
summary_es: >
  Suite de ingeniería inversa con descompilador. Lo que la hace difícil de sustituir no
  es el desensamblador, es que el descompilador y el desensamblador están sincronizados:
  renombras algo en uno y aparece renombrado en el otro.
summary_en: >
  Reverse-engineering suite with a decompiler. What makes it hard to replace is not the
  disassembler but that decompiler and disassembler stay in sync: rename something in one
  and it shows up renamed in the other.
---

<!-- es -->
La curva de aprendizaje es real y merece la pena. Mi consejo es no empezar por el
descompilador: si lees el C generado antes de entender el ensamblador que lo produjo,
acabas confiando en una reconstrucción que a veces está mal y no tienes forma de notarlo.

Para binarios pequeños suelo empezar con `objdump` y `readelf` —ver
[el artículo sobre el arranque de un ELF](/blog/lectura-de-un-binario-elf/)— y solo
cargo Ghidra cuando el tamaño lo justifica.

<!-- en -->
The learning curve is real and worth it. My advice is not to start with the decompiler:
if you read the generated C before understanding the assembly that produced it, you end
up trusting a reconstruction that is sometimes wrong with no way to notice.

For small binaries I usually start with `objdump` and `readelf` — see
[the article on ELF startup](/en/blog/elf-startup/) — and only load Ghidra when the size
justifies it.
