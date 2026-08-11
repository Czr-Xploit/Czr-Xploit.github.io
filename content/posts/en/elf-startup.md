---
title: "What happens between typing ./binary and the first byte of your main"
slug: elf-startup
lang: en
translation_key: elf-startup
type: research
date: 2026-05-09
summary: >
  Between pressing Enter and executing your first instruction there is a dynamic
  linker, a memory mapping and several decisions that determine how hard your life
  gets later. I walk the whole path using tools you already have installed.
tags: [linux, elf, reversing, binarios]
cover: /static/img/scan-loop.svg
cover_alt: "Animated scan sweep"
toc: true
---

Plenty of people doing reverse engineering learn to read disassembly before they learn
what put the addresses there in the first place. That order works right up until it
does not: the day an address does not line up, a symbol resolves to something
unexpected, or a binary behaves differently under a debugger, you need the full model.

This is the walk, without shortcuts, using nothing but `binutils` and `glibc`.

## The starting point

A minimal binary so we have something concrete:

```c title="hello.c" numbers
#include <stdio.h>

int main(void) {
    puts("hello");
    return 0;
}
```

```bash
gcc -O0 -g -o hello hello.c
file hello
```

On a modern distribution this produces a **PIE**: a position-independent executable the
kernel can load at any base address. That is why the addresses in your static
disassembly start near zero and do not match the ones you see at runtime.

::: note title="PIE changes what an address means"
In a non-PIE binary, address `0x401136` in the disassembly is the real address in
memory. In a PIE, `0x1136` is an *offset* from a base the kernel picks on each run.
Conflating the two is the first classic mistake.
:::

## Step 1: the kernel reads the headers

`execve()` knows nothing about C. What it does is read the ELF header, check the magic
number, and look at the **program headers** to work out what to map into memory.

```bash
readelf -h hello          # ELF header
readelf -l hello          # program headers (segments)
```

Two entries matter here:

| Segment type | What it means |
|:-------------|:--------------|
| `LOAD` | a chunk of the file mapped into memory, with its permissions |
| `INTERP` | the path of the interpreter that should take charge of the process |

`INTERP` is the surprising part. A dynamically linked binary does not start at its own
entry point: it tells the kernel *"run this other program and hand it control of me"*.

::: terminal title="czrxplo1t@lab"
czrxplo1t@lab:~$ readelf -l hello | grep -A1 INTERP
  INTERP         0x0000000000000318 0x0000000000000318 0x0000000000000318
      [Requesting program interpreter: /lib64/ld-linux-x86-64.so.2]
:::

That `ld-linux` is the dynamic linker, and it is what actually runs first.

## Step 2: the dynamic linker does its work

The linker resolves the shared libraries the binary needs, maps them, and resolves
symbols. You can watch the whole thing:

```bash
LD_DEBUG=libs ./hello      # what gets loaded, and from where
LD_DEBUG=bindings ./hello  # which symbol binds against which object
LD_DEBUG=help ./hello      # the rest of the channels
```

::: tip title="LD_DEBUG before strace"
When a binary loads the wrong library, `LD_DEBUG=libs` tells you in one line. `strace`
tells you too, buried under three hundred `openat` calls.
:::

Here is the detail with the most consequences: the **search order**.

```
1. DT_RPATH on the object (deprecated, but still present in real binaries)
2. LD_LIBRARY_PATH
3. DT_RUNPATH on the object
4. the /etc/ld.so.cache cache
5. the default directories (/lib, /usr/lib, ...)
```

The fact that a user-controlled environment variable sits above the system paths is
exactly why `setuid` binaries ignore `LD_LIBRARY_PATH` and `LD_PRELOAD`. If you have
ever wondered why a preloading technique "does not work" against a privileged binary,
that is why, and not a mistake on your part.

## Step 3: lazy resolution and the PLT

Function symbols are not all resolved at startup. By default they are resolved the
first time they are called, through two tables: the **PLT** (code) and the **GOT** (data).

```asm title="The first call to puts"
; the compiler does not call puts directly
call   1030 <puts@plt>

; puts@plt jumps to wherever the GOT points
1030:  jmp    QWORD PTR [rip+0x2fa2]   ; -> GOT entry for puts
1036:  push   0x0                      ; symbol index
103b:  jmp    1020 <_init+0x20>        ; -> linker resolver
```

The first time round, the GOT entry still points at the next PLT instruction, which
pushes the symbol index and jumps to the resolver. The resolver looks up `puts`,
**writes the real address into the GOT**, and jumps there. The second call goes direct.

That the GOT is writable at runtime is a property with obvious consequences, which is
why the mitigation exists:

```bash title="Check a binary's hardening"
readelf -d hello | grep -E 'BIND_NOW|FLAGS'
readelf -l hello | grep -A1 GNU_RELRO
```

- **Partial RELRO**: the GOT is reordered but remains writable.
- **Full RELRO** (`-Wl,-z,relro,-z,now`): everything resolves at startup and the GOT is
  marked read-only before control is handed over. It costs startup time and removes the
  category.

::: warning title="Do not confuse 'has RELRO' with 'is protected'"
Full RELRO protects the GOT. It does not protect function pointers on the heap, method
tables, or callbacks registered at runtime. It is a specific mitigation against a
specific vector.
:::

## Step 4: finally, your `main`

When the linker finishes, it jumps to the binary's real entry point, which is **not
`main`**. It is `_start`, which sets up the stack and calls the libc startup routine,
which in turn runs the constructors and finally calls `main`.

```bash
readelf -h hello | grep Entry     # address of _start
nm hello | grep -w _start
objdump -d --section=.init_array hello
```

Constructors in `.init_array` run **before** your `main`. That detail matters in
reverse engineering: code that executes before the thing you are looking at.

## Checking it all at once

A small script that summarises a binary's posture:

```python title="posture.py" numbers highlight="8,14"
#!/usr/bin/env python3
"""Quick summary of an ELF's hardening posture."""
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
    print(f"{name:<10} {'yes' if value else 'no'}")
```

The last two rows are the interesting ones in an assessment: an `RPATH` or `RUNPATH`
pointing at a writable directory is a problem, and it turns up more often than it
should in hand-packaged software.

## The summary

::: timeline title="From Enter to main"
- execve — the kernel validates the ELF header and maps the LOAD segments
- INTERP — control passes to /lib64/ld-linux, not to the binary
- ld.so — resolves libraries following the search order, maps them, processes relocations
- _start — sets up the stack and calls the libc startup routine
- .init_array — constructors run
- main — your first line
:::

If you take away one idea: **the binary is not what starts**. Almost everything strange
you will see at runtime happens in the four steps before your code.

::: references
- `man 5 elf`, `man 8 ld.so`, `man 1 readelf`
- [ELF specification — Tool Interface Standard](https://refspecs.linuxfoundation.org/elf/elf.pdf)
:::
