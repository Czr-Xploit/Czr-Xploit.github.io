---
name: Volatility 3
slug: volatility
url: https://github.com/volatilityfoundation/volatility3
category: forensics
tags: [forense, memoria, respuesta]
license: Volatility Software License 1.0
language: Python
featured: false
summary_es: >
  Análisis forense de volcados de memoria. Lo tengo aquí porque la memoria contiene lo
  que el disco nunca vio: claves en claro, procesos que ya no existen y conexiones
  cerradas. Si solo analizas disco, estás mirando la mitad de la escena.
summary_en: >
  Memory-dump forensics. It is here because memory holds what disk never saw: keys in the
  clear, processes that no longer exist, and closed connections. If you only analyse
  disk, you are looking at half the scene.
---

<!-- es -->
El error de principiante es tratar el volcado como un sistema de ficheros. No lo es: es
una fotografía de estado, y el orden en que la interrogas cambia lo que encuentras.
Empieza siempre por la lista de procesos y las conexiones, no por buscar cadenas.

La versión 3 rompió compatibilidad con los plugins de la 2 y no todos se han portado.
Comprueba que el plugin que necesitas existe antes de planificar el análisis alrededor
de él.

<!-- en -->
The beginner mistake is treating the dump as a filesystem. It is not: it is a snapshot of
state, and the order in which you interrogate it changes what you find. Always start with
the process list and connections, not with string searching.

Version 3 broke compatibility with version 2 plugins and not all have been ported. Check
that the plugin you need exists before planning an analysis around it.
