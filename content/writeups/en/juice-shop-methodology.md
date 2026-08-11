---
title: "Juice Shop: enumeration methodology on a deliberately vulnerable app"
slug: juice-shop-methodology
lang: en
translation_key: juice-shop-methodology
type: writeup
date: 2026-06-18
platform: OWASP
difficulty: Easy
os: Docker
techniques: [enumeration, client-side analysis, access control, business logic]
summary: >
  This is not a solutions writeup. It is the record of how I approach a web application
  I do not know: what I look at first, in what order, and the three hypotheses I
  discarded before finding anything.
tags: [web, laboratorio, metodologia, enumeracion]
toc: true
---

::: warning title="Lab environment"
Everything below runs against a local instance of **OWASP Juice Shop**, an application
built explicitly to be attacked for training purposes. None of it applies to third-party
systems without written authorisation. The app runs locally and is never exposed to the
internet.
:::

## Why this writeup has no solutions in it

Challenge writeups are usually a list of commands that worked. They are useless for
learning, because the real work is not running the right command: it is deciding which
one to try when you have twenty options and no hints.

So this is the record of the decisions, mistakes included.

::: terminal title="czrxplo1t@lab"
czrxplo1t@lab:~$ docker run --rm -p 127.0.0.1:3000:3000 bkimminich/juice-shop
czrxplo1t@lab:~$ curl -sI http://127.0.0.1:3000/ | head -5
:::

## Phase 1: what is this, before touching anything

Before launching a single tool I spend ten minutes reading. It is the phase most people
skip and the one that saves the most time.

What I look at, in this order:

1. **The landing page response.** Headers, cookies, declared technology.
2. **The JavaScript bundle.** In a SPA, the client contains the map of the API.
3. **The client-side routes.** The front-end router declares views that may not be linked anywhere.
4. **The usual files:** `robots.txt`, `sitemap.xml`, `/.well-known/`, `package.json` if it happens to be served.

::: tip title="The bundle before the scanner"
A directory scanner guesses paths. The SPA bundle *tells* you them. Pulling
endpoint-shaped strings out of a minified bundle gets better results in two minutes than
a wordlist attack does in twenty.
:::

```bash title="Extracting endpoint candidates from the bundle"
# Download the bundles the landing page references
curl -s http://127.0.0.1:3000/ \
  | grep -oE 'src="[^"]+\.js"' \
  | cut -d'"' -f2 \
  | while read -r path; do curl -s "http://127.0.0.1:3000/${path#/}" -o "$(basename "$path")"; done

# Look for strings shaped like API routes
grep -ohE '"/(api|rest)/[a-zA-Z0-9/_-]+"' ./*.js | sort -u
```

That produces the API inventory without having sent a single suspicious request.

## Phase 2: the first hypothesis, and why it was a bad one

With the inventory in front of me, my first instinct was the usual one: look for
injection in the search parameters.

**Hypothesis 1: the search endpoint concatenates input into a query.**

It is a reasonable hypothesis and it is the one everybody teaches. The problem is that I
adopted it *because it was the one I knew how to test*, not because the evidence pointed
there. That is tool bias, and it has cost me hours more than once.

What I should have asked first, and what I always ask now:

- What does this application do that is *specific to its business*?
- Where is there an operation that crosses data between two different users?
- Which endpoint returns more information than the interface displays?

The third question is the one that produces results most consistently, and it requires
injecting nothing at all.

::: spoiler title="What I found comparing the API response against the interface"
Several endpoints return complete objects and the front-end drops fields at render time.
It is a common pattern in SPAs built quickly: the filtering happens on the client, where
the attacker controls the code. Comparing `curl` against what you see on screen is one
of the best effort-to-result checks there is.

The general lesson is not "this endpoint leaks data." It is: **the interface is not a
security control**, and any filtering that happens after the bytes leave the server is
not filtering.
:::

## Phase 3: the second hypothesis, discarded by measurement

**Hypothesis 2: access control on another user's resources is non-existent.**

Here there was real signal: object identifiers were sequential and visible. The check is
direct and non-destructive — request an identifier that isn't yours and look at the
status code. Nothing needs to be modified.

And I still discarded it, because **I measured before concluding**:

```bash title="Access-control check, non-destructive" numbers highlight="6"
# Authenticate as user A and keep the token
TOKEN_A=$(curl -s -X POST http://127.0.0.1:3000/rest/user/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@lab.local","password":"..."}' | grep -oE '"token":"[^"]+"' | cut -d'"' -f4)

# Request resources by identifier and keep only the status code
for id in $(seq 1 10); do
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer $TOKEN_A" \
    "http://127.0.0.1:3000/api/BasketItems/$id")
  echo "$id -> $code"
done
```

The result was not what I expected: the application **does** check ownership on that
particular endpoint. My hypothesis was reasonable and it was wrong, and the only way to
know was to measure it instead of assuming.

::: note title="This is 80% of the work"
A normal writeup would have deleted this entire section, because it "led nowhere." But
discarding a hypothesis with evidence **is** progress: it shrinks the search space and
tells you where not to look again. What is not progress is trying things at random and
remembering only the one that worked.
:::

## Phase 4: the question that did produce signal

I went back to the third question from phase 2 — *which endpoint returns more than the
interface shows?* — and applied it systematically instead of by intuition:

| Check | Cost | Signal produced |
|:------|:-----|:----------------|
| Compare API JSON against the rendered DOM | low | high |
| Look for fields present in the response and absent on screen | low | high |
| Review error responses for verbosity | low | medium |
| Enumerate sequential identifiers | low | low (here) |
| Fuzz search parameters | high | none (here) |

The table is the actual result of the session, and the order I should have worked in
from the start: **ascending cost, descending signal**.

::: spoiler title="The pattern that turned out to be the way in"
The divergence between what the API returns and what the front-end paints. In a SPA
built in a hurry, the backend tends to serialise the whole model and delegate filtering
to the client template — where the attacker controls execution.

Spotting it needs no specialised tooling: `curl` the endpoint, look at the screen,
compare. If the response contains fields the interface never displays, that is your way
in, and you have not sent a single request a WAF would flag.
:::

## Session timeline

::: timeline title="How the time actually broke down"
- 00:00–00:10 — Passive reading: headers, cookies, client bundle. Zero suspicious requests.
- 00:10–00:25 — API inventory extracted from the bundle. The whole map, without scanning.
- 00:25–00:50 — Hypothesis 1 (search injection). Discarded. Tool bias.
- 00:50–01:05 — Hypothesis 2 (access control). Measured and discarded with evidence.
- 01:05–01:20 — API-versus-interface comparison. Signal within four minutes.
- 01:20–01:40 — Confirmation and notes.
:::

The two discarded hypotheses took **40 of the 100 minutes**. That is not wasted time: it
is the price of shrinking the search space, and it is exactly the part conventional
writeups delete.

## Lessons

- [x] Read before scanning. A SPA's client is the map of the API, for free.
- [x] Order checks by ascending cost and descending signal, not by what you are best at.
- [x] Measure to discard. A hypothesis discarded with evidence beats three left untested.
- [x] Distrust tool bias: the technique you know best is not the one the evidence points at.
- [ ] Automate the API-versus-DOM comparison. It is still manual and it shouldn't be.

::: warning title="On extrapolating"
Juice Shop is a lab: its flaws are placed on purpose and their density looks nothing like
a real application's. What transfers is **the method** — the order of the checks and the
discipline of measuring — not the specific conclusions.
:::

## Mitigation

For whoever builds, not whoever audits. The three patterns that showed up here are all
fixed on the server side:

1. **Serialise only what the view needs.** An explicit DTO per endpoint, never the full
   model. If the filtering happens on the client, it is not filtering.
2. **Check ownership on every resource access**, not just on the one exercised during
   development. The check belongs in the data layer, not the controller.
3. **Uniform error responses.** A 404 and a 403 that can be told apart are a free
   enumeration oracle.

And on the detection side: alerting when one authenticated user requests sequential
identifiers is a cheap rule that catches the whole of phase 3 of this writeup.

::: references
- [OWASP Juice Shop](https://owasp.org/www-project-juice-shop/) — the lab used here
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/) — API1 and API3 cover both patterns in this writeup
- [OWASP Web Security Testing Guide](https://owasp.org/www-project-web-security-testing-guide/) — the formal methodology behind the phase ordering
:::
