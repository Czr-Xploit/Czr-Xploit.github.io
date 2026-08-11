---
title: "Juice Shop: metodología de enumeración en una app deliberadamente vulnerable"
slug: juice-shop-metodologia
lang: es
translation_key: juice-shop-methodology
type: writeup
date: 2026-06-18
platform: OWASP
difficulty: Fácil
os: Docker
techniques: [enumeración, análisis de cliente, control de acceso, lógica de negocio]
summary: >
  No es un writeup de soluciones. Es el registro de cómo abordo una aplicación web que
  no conozco: qué miro primero, en qué orden, y las tres hipótesis que descarté antes
  de encontrar algo.
tags: [web, laboratorio, metodologia, enumeracion]
toc: true
---

::: warning title="Entorno de laboratorio"
Todo lo que sigue se ejecuta contra una instancia local de **OWASP Juice Shop**, una
aplicación diseñada explícitamente para ser atacada con fines formativos. Nada de esto
se aplica a sistemas de terceros sin autorización escrita. La app se levanta en local y
no se expone a internet.
:::

## Por qué este writeup no lleva soluciones

Los writeups de retos suelen ser una lista de comandos que funcionaron. Son inútiles
para aprender, porque el trabajo real no es ejecutar el comando correcto: es decidir
cuál probar cuando tienes veinte opciones y ninguna pista.

Así que esto es el registro de decisiones, con los errores dentro.

::: terminal title="czrxplo1t@lab"
czrxplo1t@lab:~$ docker run --rm -p 127.0.0.1:3000:3000 bkimminich/juice-shop
czrxplo1t@lab:~$ curl -sI http://127.0.0.1:3000/ | head -5
:::

## Fase 1: qué es esto antes de tocar nada

Antes de lanzar una sola herramienta dedico diez minutos a leer. Es la fase que más
gente se salta y la que más tiempo ahorra.

Lo que miro, en este orden:

1. **La respuesta de la portada.** Cabeceras, cookies, tecnología declarada.
2. **El bundle de JavaScript.** En una SPA, el cliente contiene el mapa de la API.
3. **Las rutas del cliente.** El router del front declara vistas que quizá no estén enlazadas.
4. **Los ficheros de siempre:** `robots.txt`, `sitemap.xml`, `/.well-known/`, `package.json` si está servido.

::: tip title="El bundle antes del escáner"
Un escáner de directorios adivina rutas. El bundle de la SPA *te las dice*. Extraer las
cadenas que parecen endpoints de un bundle minificado da mejores resultados en dos
minutos que un ataque de diccionario en veinte.
:::

```bash title="Extraer candidatos a endpoint del bundle"
# Descargar los bundles que referencia la portada
curl -s http://127.0.0.1:3000/ \
  | grep -oE 'src="[^"]+\.js"' \
  | cut -d'"' -f2 \
  | while read -r path; do curl -s "http://127.0.0.1:3000/${path#/}" -o "$(basename "$path")"; done

# Buscar cadenas con forma de ruta de API
grep -ohE '"/(api|rest)/[a-zA-Z0-9/_-]+"' ./*.js | sort -u
```

Esto produce el inventario de la API sin haber enviado una sola petición sospechosa.

## Fase 2: la primera hipótesis, y por qué era mala

Con el inventario delante, mi primer instinto fue el habitual: buscar inyección en los
parámetros de búsqueda.

**Hipótesis 1: el endpoint de búsqueda concatena la entrada en una consulta.**

Es una hipótesis razonable y es la que enseña todo el mundo. El problema es que la
adopté *porque era la que sabía probar*, no porque la evidencia apuntara ahí. Eso es
sesgo de herramienta, y me ha costado horas más de una vez.

Lo que debí preguntarme primero, y lo que pregunto ahora siempre:

- ¿Qué hace esta aplicación que sea *específico de su negocio*?
- ¿Dónde hay una operación que cruce datos entre dos usuarios distintos?
- ¿Qué endpoint devuelve más información de la que la interfaz muestra?

La tercera pregunta es la que produce resultados con más consistencia, y no requiere
inyectar nada.

::: spoiler title="Qué encontré al comparar la respuesta de la API con la interfaz"
Varios endpoints devuelven objetos completos y el front descarta campos al renderizar.
Es un patrón habitual en SPAs construidas rápido: el filtrado ocurre en el cliente,
donde el atacante controla el código. Comparar `curl` contra lo que ves en pantalla es
una de las comprobaciones con mejor relación esfuerzo/resultado que existen.

La lección general no es «este endpoint filtra datos». Es: **la interfaz no es un
control de seguridad**, y cualquier filtrado que ocurra después de que los bytes salgan
del servidor no es filtrado.
:::

## Fase 3: la segunda hipótesis, descartada por medición

**Hipótesis 2: el control de acceso a los recursos de otro usuario es inexistente.**

Aquí sí había señal: los identificadores de objeto eran secuenciales y visibles. La
comprobación es directa y no destructiva — pedir un identificador que no te pertenece y
mirar el código de estado. No hace falta modificar nada.

Y aun así la descarté, porque **medí antes de concluir**:

```bash title="Comprobación de control de acceso, no destructiva" numbers highlight="6"
# Autenticarse como usuario A y guardar el token
TOKEN_A=$(curl -s -X POST http://127.0.0.1:3000/rest/user/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@lab.local","password":"..."}' | grep -oE '"token":"[^"]+"' | cut -d'"' -f4)

# Pedir recursos por identificador y quedarse solo con el código de estado
for id in $(seq 1 10); do
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $TOKEN_A" \
    "http://127.0.0.1:3000/api/BasketItems/$id")
  echo "$id -> $code"
done
```

El resultado no fue el que esperaba: la aplicación **sí** comprueba la propiedad en ese
endpoint concreto. Mi hipótesis era razonable y estaba equivocada, y la única forma de
saberlo fue medirlo en lugar de asumirlo.

::: note title="Esto es el 80% del trabajo"
Un writeup normal habría borrado esta sección entera, porque «no llevó a nada». Pero
descartar una hipótesis con evidencia **es** progreso: reduce el espacio de búsqueda y
te dice dónde no volver a mirar. Lo que no es progreso es probar cosas al azar y
recordar solo la que funcionó.
:::

## Fase 4: la pregunta que sí produjo señal

Volví a la tercera pregunta de la fase 2 — *¿qué endpoint devuelve más de lo que la
interfaz muestra?* — y la apliqué de forma sistemática en vez de por intuición:

| Comprobación | Coste | Señal producida |
|:-------------|:------|:----------------|
| Comparar JSON de la API contra el DOM renderizado | bajo | alta |
| Buscar campos presentes en la respuesta y ausentes en pantalla | bajo | alta |
| Revisar respuestas de error por verbosidad | bajo | media |
| Enumerar identificadores secuenciales | bajo | baja (aquí) |
| Fuzzing de parámetros de búsqueda | alto | ninguna (aquí) |

La tabla es el resultado real de la sesión, y el orden en que debí haber trabajado desde
el principio: **coste ascendente, señal descendente**.

::: spoiler title="El patrón que acabó siendo la vía"
La divergencia entre lo que devuelve la API y lo que pinta el front. En una SPA
construida con prisa, el backend suele serializar el modelo entero y delegar el filtrado
en la plantilla del cliente — donde el atacante controla la ejecución.

Detectarlo no requiere ninguna herramienta especializada: `curl` el endpoint, mira la
pantalla, compara. Si la respuesta contiene campos que la interfaz nunca muestra, ahí
tienes tu vía, y no has enviado una sola petición que un WAF marcaría.
:::

## Cronología de la sesión

::: timeline title="Cómo se repartió el tiempo de verdad"
- 00:00–00:10 — Lectura pasiva: cabeceras, cookies, bundle del cliente. Cero peticiones sospechosas.
- 00:10–00:25 — Inventario de la API extraído del bundle. El mapa completo sin escanear.
- 00:25–00:50 — Hipótesis 1 (inyección en búsqueda). Descartada. Sesgo de herramienta.
- 00:50–01:05 — Hipótesis 2 (control de acceso). Medida y descartada con evidencia.
- 01:05–01:20 — Comparación API contra interfaz. Señal a los cuatro minutos.
- 01:20–01:40 — Confirmación y notas.
:::

Las dos hipótesis descartadas se llevaron **40 de los 100 minutos**. Eso no es tiempo
perdido: es el precio de reducir el espacio de búsqueda, y es exactamente la parte que
los writeups convencionales borran.

## Lecciones

- [x] Leer antes de escanear. El cliente de una SPA es el mapa de la API, gratis.
- [x] Ordenar las comprobaciones por coste ascendente y señal descendente, no por lo que sabes hacer mejor.
- [x] Medir para descartar. Una hipótesis descartada con evidencia vale más que tres sin comprobar.
- [x] Desconfiar del sesgo de herramienta: la técnica que mejor dominas no es la que la evidencia señala.
- [ ] Automatizar la comparación API-contra-DOM. Sigue siendo manual y no debería.

::: warning title="Sobre extrapolar"
Juice Shop es un laboratorio: sus fallos están puestos a propósito y su densidad no se
parece a la de una aplicación real. Lo que se transfiere es **el método** —el orden de
las comprobaciones y la disciplina de medir— no las conclusiones concretas.
:::

## Mitigación

Para quien construye, no para quien audita. Los tres patrones que aparecieron aquí se
corrigen del lado del servidor:

1. **Serializar solo lo que la vista necesita.** Un DTO explícito por endpoint, nunca el
   modelo completo. Si el filtrado ocurre en el cliente, no es filtrado.
2. **Comprobar la propiedad en cada acceso a recurso**, no solo en el que se probó
   durante el desarrollo. La comprobación pertenece a la capa de datos, no al controlador.
3. **Respuestas de error uniformes.** Un 404 y un 403 que se distinguen son un oráculo
   de enumeración gratuito.

Y del lado de la detección: alertar sobre un mismo usuario autenticado pidiendo
identificadores secuenciales es una regla barata que captura la fase 3 de este writeup
entera.

::: references
- [OWASP Juice Shop](https://owasp.org/www-project-juice-shop/) — el laboratorio usado aquí
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/) — API1 y API3 cubren los dos patrones de este writeup
- [OWASP Web Security Testing Guide](https://owasp.org/www-project-web-security-testing-guide/) — la metodología formal detrás del orden de fases
:::