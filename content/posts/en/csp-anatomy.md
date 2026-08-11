---
title: "Anatomy of a CSP: why almost every policy I read does nothing"
slug: csp-anatomy
lang: en
translation_key: csp-anatomy
type: research
date: 2026-07-22
updated: 2026-08-11
featured: true
pinned: true
summary: >
  A badly written Content-Security-Policy provides a sense of security that is not
  there. I take apart the three constructions that appear in almost every real policy
  and explain how each one hands script execution back to the attacker.
tags: [web, csp, xss, defensa, navegador]
toc: true
---

I have spent years reading `Content-Security-Policy` headers during assessments, and
the pattern repeats: the policy exists, the team considers the control closed, and yet
it does not stop injected script from running. CSP is a good mechanism. The problem is
that its configuration surface is enormous and most tutorials teach precisely the
constructions that neutralise it.

This is a teardown of the three I meet most often.

## What a CSP actually does

Before the teardown, the correct mental model.

A CSP is a set of rules the server sends to the browser, which the browser enforces
against **the resources the page tries to load or execute**. It does not filter input,
it does not escape output, and it does not prevent an injection from existing. What it
does is reduce what an attacker can *do* with an injection that already exists.

::: note title="The distinction that matters"
CSP is a second line of defence. If your only control against XSS is the CSP, the
problem is not the policy: it is that you are not escaping output.
:::

The header is a list of directives separated by `;`, each with a list of permitted
sources:

```http title="HTTP response"
HTTP/2 200
content-type: text/html; charset=utf-8
content-security-policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'
```

`default-src` is the fallback for fetch directives that are not declared explicitly.
The ones that do **not** inherit from `default-src` are the first trap, and we get to
them at the end.

## Failure 1: `script-src 'unsafe-inline'`

By far the most common, and the most terminal.

```http
content-security-policy: default-src 'self'; script-src 'self' 'unsafe-inline'
```

`'unsafe-inline'` lets the browser execute any inline `<script>` and any `on*`
attribute. That is exactly the vector a reflected or stored XSS uses. With this
directive present, the policy contributes **nothing** against XSS:

```html title="The payload the policy permits"
<img src=x onerror="fetch('/api/me').then(r=>r.json()).then(d=>navigator.sendBeacon('/collect',JSON.stringify(d)))">
```

The reason it appears so often is mechanical: somebody adds the CSP, the page breaks
because it has inline scripts, and `'unsafe-inline'` makes it stop breaking. The ticket
gets closed.

### What to do instead

There are three real ways out, in order of preference:

1. **Externalise everything.** Every inline `<script>` becomes a file served from the
   same origin. It is the cleanest option and it is what this site does: the policy is
   `script-src 'self'` with no exceptions.
2. **Per-response nonces.** The server generates a random value per response and places
   it both in the header and on every `<script nonce="...">`.
3. **Hashes.** For inline scripts that never change, `'sha256-...'` of the exact content.

::: warning title="A nonce is only worth anything if it is unpredictable"
A nonce reused across responses, derived from the session ID, or generated with a
non-cryptographic PRNG is a nonce the attacker can guess or extract. It has to come
from a CSPRNG and differ on every response. If your page is statically cached, nonces
are not the right tool.
:::

```python title="Correct nonce generation" highlight="6,11"
import secrets
from flask import g, render_template, make_response

@app.before_request
def issue_nonce():
    # 128 bits from the system CSPRNG, one per response.
    g.csp_nonce = secrets.token_urlsafe(16)

@app.after_request
def apply_csp(response):
    policy = (
        "default-src 'none'; "
        f"script-src 'self' 'nonce-{g.csp_nonce}'; "
        "style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["Content-Security-Policy"] = policy
    return response
```

## Failure 2: wildcards and CDNs in `script-src`

The second construction I see constantly:

```http
content-security-policy: script-src 'self' https://cdn.example.com https://*.googleapis.com
```

The reasoning is "I only allow trusted origins". The problem is that an origin is not a
useful unit of trust when that origin hosts third-party content.

Many public CDNs serve arbitrary libraries under arbitrary paths. If an attacker can
load any file from that origin, they can go looking for one that gives them indirect
execution: an old version of a library with a known gadget, or an endpoint that returns
JavaScript derived from a parameter.

::: danger title="The JSONP case"
A JSONP endpoint on an allowed origin turns the policy into decoration. The attacker
injects `<script src="https://allowed-origin/api?callback=alert(1)//">` and the trusted
origin itself returns the attacker's code, with the CSP's blessing.
:::

The practical rule: **an origin in `script-src` is only as strong as the weakest
content that origin will serve to anyone**. If you do not control everything hosted
there, it is not a trusted origin.

The alternative is self-hosting. It costs a few kilobytes and removes the entire class:

```bash title="Self-host instead of trusting a CDN"
# Instead of <script src="https://cdn.example.com/lib@3.2.1/dist/lib.min.js">
curl -fsSLO https://cdn.example.com/lib@3.2.1/dist/lib.min.js
sha384sum lib.min.js          # compare against the hash the project publishes
mv lib.min.js static/vendor/
```

## Failure 3: forgetting the directives that do not inherit

The subtlest one, and the one that separates a hand-written policy from a copied one.

`default-src` does **not** cover every directive. These are independent, and if you do
not declare them they are unrestricted:

| Directive | If omitted | Consequence |
|:----------|:-----------|:------------|
| `base-uri` | unrestricted | an injected `<base href>` rewrites every relative URL |
| `form-action` | unrestricted | forms can post to an attacker's host |
| `frame-ancestors` | unrestricted | the page is framable: clickjacking |
| `sandbox` | not applied | — |
| `report-uri` / `report-to` | no reports | you lose the telemetry |

`base-uri` is the one people most underestimate. With a limited HTML injection — no
`<script>`, no `on*` — this is enough:

```html
<base href="https://attacker.tld/">
```

From that point on, every relative `<script src="app.js">` on the page resolves against
the attacker's domain. `script-src 'self'` does not help: as far as the browser is
concerned, the script is loading from the origin `<base>` has just declared.

This is why this site declares `base-uri 'none'` and `default-src 'none'`, and then
adds each directive it actually needs.

## A policy that does work

A starting point for an application serving dynamic HTML:

```http title="Defensible baseline"
content-security-policy:
  default-src 'none';
  script-src 'self';
  style-src 'self';
  img-src 'self' data:;
  font-src 'self';
  connect-src 'self';
  manifest-src 'self';
  media-src 'self';
  base-uri 'none';
  form-action 'self';
  frame-ancestors 'none';
  object-src 'none';
  upgrade-insecure-requests
```

`default-src 'none'` as the base means everything you have not explicitly permitted is
blocked. It is uncomfortable to deploy, and that discomfort is exactly why it works: it
forces you to enumerate what the application really loads.

## How to verify it properly

Do not settle for the header being present. Verify that it does what you think.

::: terminal title="czrxplo1t@lab"
czrxplo1t@lab:~$ curl -sI https://example.tld/ | grep -i content-security-policy
content-security-policy: default-src 'none'; script-src 'self'; base-uri 'none'
czrxplo1t@lab:~$ curl -s https://example.tld/ | grep -coE '<script(?![^>]*src=)'
0
:::

The three checks I always run:

- [x] The header is on **every** HTML response, not just the landing page.
- [x] The policy contains no `'unsafe-inline'` or `'unsafe-eval'` in `script-src`.
- [x] `base-uri`, `form-action`, `frame-ancestors` and `object-src` are all declared.
- [ ] A `report-to` endpoint is collecting violations in production.[^report]

::: spoiler title="Why the last one is unticked in most assessments"
Because almost nobody deploys it. Violation reports are the only way to learn that your
policy is breaking something for real users before support tells you. Rolling out in
`Content-Security-Policy-Report-Only` first, collecting a week of reports, and only then
switching to enforcing mode is the difference between a policy that survives and one
somebody disables on Tuesday.
:::

## What the defender takes away

Three sentences:

1. `'unsafe-inline'` in `script-src` voids the policy against XSS. There is no nuance here.
2. A third-party origin in `script-src` is only as strong as the worst file it serves.
3. `default-src` does not cover `base-uri`, `form-action` or `frame-ancestors`. Declare them.

::: references
- [Content Security Policy Level 3 — W3C](https://www.w3.org/TR/CSP3/)
- [CSP on MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy)
- [OWASP Content Security Policy Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)
:::

[^report]: `report-uri` is deprecated in favour of `report-to`, but browser support for `report-to` is not universal. Declaring both remains the pragmatic option.
