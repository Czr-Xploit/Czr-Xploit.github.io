---
title: "Qué pasa entre que escribes ./binario y el primer byte de tu main"
slug: lectura-de-un-binario-elf
lang: es
translation_key: elf-startup
type: research
date: 2026-05-09
summary: >
  Entre pulsar Enter y ejecutar tu primera instrucción hay un enlazador dinámico, un
  mapeo de memoria y varias decisiones que determinan lo dura que será tu vida más
  tarde. Recorro el camino con herramientas que ya tienes instaladas.
tags: [linux, elf, reversing, binarios]
cover: /static/img/scan-loop.svg
cover_alt: "Barrido animado de un escaneo"
toc: true
---

Mucha gente que hace reversing sabe leer desensamblado antes de saber qué ha puesto ahí
las direcciones que está leyendo. Es un orden de aprendizaje que funciona hasta que deja
de funcionar: el día que la dirección no cuadra, que un símbolo se resuelve a algo
inesperado o que un binario se comporta distinto bajo depurador, hace falta el modelo
completo.

Este es el recorrido, sin atajos, usando solo `binutils` y `glibc`.

## El punto de partida

Un binario mínimo para tener algo concreto:

```c title="hola.c" numbers
#include <stdio.h>

int main(void) {
    puts("hola");
    return 0;
}
```

```bash
gcc -O0 -g -o hola hola.c
file hola
```

En una distribución moderna esto produce un **PIE**: un ejecutable independiente de
posición, que el kernel puede cargar en cualquier dirección base. Es la razón por la
que las direcciones que ves en el desensamblado estático empiezan cerca de cero y no
coinciden con las de tiempo de ejecución.

::: note title="PIE cambia lo que significa una dirección"
En un binario no-PIE, la dirección `0x401136` del desensamblado es la dirección real en
memoria. En un PIE, `0x1136` es un *desplazamiento* respecto a una base que el kernel
elige en cada ejecución. Confundir ambos es el primer error clásico.
:::

## Paso 1: el kernel lee las cabeceras

`execve()` no sabe nada de C. Lo que hace es leer la cabecera ELF, comprobar el número
mágico, y mirar las **cabeceras de programa** para saber qué mapear en memoria.

```bash
readelf -h hola          # cabecera ELF
readelf -l hola          # cabeceras de programa (segmentos)
```

Dos entradas importan aquí:

| Tipo de segmento | Qué significa |
|:-----------------|:--------------|
| `LOAD` | un trozo del fichero que se mapea en memoria, con sus permisos |
| `INTERP` | la ruta del intérprete que debe hacerse cargo del proceso |

`INTERP` es la parte que sorprende. Un binario enlazado dinámicamente no arranca por su
propio punto de entrada: le dice al kernel *«ejecuta a este otro programa y pásale mi
control»*.

::: terminal title="czrxplo1t@lab"
czrxplo1t@lab:~$ readelf -l hola | grep -A1 INTERP
  INTERP         0x0000000000000318 0x0000000000000318 0x0000000000000318
      [Requesting program interpreter: /lib64/ld-linux-x86-64.so.2]
:::

Ese `ld-linux` es el enlazador dinámico, y es quien realmente arranca primero.

## Paso 2: el enlazador dinámico hace su trabajo

El enlazador resuelve las bibliotecas compartidas que el binario necesita, las mapea, y
resuelve los símbolos. Lo puedes observar entero:

```bash
LD_DEBUG=libs ./hola      # qué se carga y desde dónde
LD_DEBUG=bindings ./hola  # qué símbolo se resuelve contra qué objeto
LD_DEBUG=help ./hola      # el resto de canales
```

::: tip title="LD_DEBUG antes que strace"
Cuando un binario carga la biblioteca equivocada, `LD_DEBUG=libs` te lo dice en una
línea. `strace` te lo dice también, enterrado entre trescientas llamadas a `openat`.
:::

Aquí aparece el detalle que más consecuencias tiene: el **orden de búsqueda**.

```
1. DT_RPATH del objeto (obsoleto, pero todavía presente en binarios reales)
2. LD_LIBRARY_PATH
3. DT_RUNPATH del objeto
4. la caché de /etc/ld.so.cache
5. los directorios por defecto (/lib, /usr/lib, ...)
```

Que una variable de entorno controlada por el usuario esté por encima de las rutas del
sistema es exactamente la razón por la que los binarios `setuid` ignoran
`LD_LIBRARY_PATH` y `LD_PRELOAD`. Si alguna vez te preguntas por qué una técnica de
precarga «no funciona» contra un binario privilegiado, es esto y no un fallo tuyo.

## Paso 3: resolución perezosa y la PLT

Los símbolos de función no se resuelven todos al arrancar. Por defecto se resuelven la
primera vez que se llaman, mediante dos tablas: la **PLT** (código) y la **GOT** (datos).

```asm title="La primera llamada a puts"
; el compilador no llama a puts directamente
call   1030 <puts@plt>

; puts@plt salta a donde apunte la GOT
1030:  jmp    QWORD PTR [rip+0x2fa2]   ; -> entrada GOT de puts
1036:  push   0x0                      ; índice del símbolo
103b:  jmp    1020 <_init+0x20>        ; -> resolvedor del enlazador
```

La primera vez, la entrada de la GOT todavía apunta a la instrucción siguiente de la
PLT, que empuja el índice del símbolo y salta al resolvedor. El resolvedor busca `puts`,
**escribe la dirección real en la GOT**, y salta ahí. La segunda llamada ya va directa.

Que la GOT sea escribible en tiempo de ejecución es una propiedad con consecuencias
obvias, y por eso existe la mitigación:

```bash title="Comprobar el endurecimiento del binario"
readelf -d hola | grep -E 'BIND_NOW|FLAGS'
readelf -l hola | grep -A1 GNU_RELRO
```

- **RELRO parcial**: la GOT se reordena pero sigue siendo escribible.
- **RELRO completo** (`-Wl,-z,relro,-z,now`): todo se resuelve al arrancar y la GOT se
  marca de solo lectura antes de ceder el control. Cuesta arranque, elimina la categoría.

::: warning title="No confundas «tiene RELRO» con «está protegido»"
RELRO completo protege la GOT. No protege punteros a función en el heap, ni tablas de
métodos, ni callbacks registrados en tiempo de ejecución. Es una mitigación concreta
contra un vector concreto.
:::

## Paso 4: por fin, tu `main`

Cuando el enlazador termina, salta al punto de entrada real del binario, que **no es
`main`**. Es `_start`, que prepara la pila y llama a la rutina de arranque de la libc,
que a su vez ejecuta los constructores y finalmente llama a `main`.

```bash
readelf -h hola | grep Entry     # dirección de _start
nm hola | grep -w _start
objdump -d --section=.init_array hola
```

Los constructores de `.init_array` corren **antes** que tu `main`. Es un detalle que
importa en reversing: código que se ejecuta antes de lo que estás mirando.

## Verificarlo todo de una vez

Un script pequeño que resume la postura de un binario:

```python title="postura.py" numbers highlight="8,14"
#!/usr/bin/env python3
"""Resumen rápido de la postura de endurecimiento de un ELF."""
import subprocess, sys

def run(*args):
    return subprocess.run(args, capture_output=True, text=True).stdout

path = sys.argv[1]
headers, dynamic, segments = run("readelf", "-h", path), run("readelf", "-d", path), run("readelf", "-lW", path)

checks = {
    "PIE":        "Type:" in headers and "DYN" in headers,
    "RELRO":      "GNU_RELRO" in segments,
    "BIND_NOW":   "BIND_NOW" in dynamic or "NOW" in dynamic,
    "NX":         "GNU_STACK" in segments and "RWE" not in segments,
    "RPATH":      "RPATH" in dynamic,
    "RUNPATH":    "RUNPATH" in dynamic,
}
for name, value in checks.items():
    print(f"{name:<10} {'sí' if value else 'no'}")
```

Las dos últimas filas son las interesantes en una auditoría: un `RPATH` o `RUNPATH`
apuntando a un directorio escribible es un problema, y aparece más de lo que debería en
software empaquetado a mano.

## El resumen

::: timeline title="De Enter a main"
- execve — el kernel valida la cabecera ELF y mapea los segmentos LOAD
- INTERP — el control pasa a /lib64/ld-linux, no al binario
- ld.so — resuelve bibliotecas siguiendo el orden de búsqueda, mapea, procesa reubicaciones
- _start — prepara la pila y llama a la rutina de arranque de la libc
- .init_array — corren los constructores
- main — tu primera línea
:::

Si te llevas una sola idea: **el binario no es quien arranca**. Casi todo lo raro que
verás en tiempo de ejecución ocurre en los cuatro pasos anteriores a tu código.

::: references
- `man 5 elf`, `man 8 ld.so`, `man 1 readelf`
- [ELF specification — Tool Interface Standard](https://refspecs.linuxfoundation.org/elf/elf.pdf)
:::
