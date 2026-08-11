---
title: Contact
slug: contact
lang: en
translation_key: contact
type: page
date: 2026-01-15
summary: How to write to me, how to encrypt it, and what to expect back.
tags: [meta]
toc: false
---

## Channels

| Channel | For | Response time |
|:--------|:----|:--------------|
| Email | Everything else | 3–7 days |
| `security.txt` | Reporting something about **this** site | 72 h |
| GitHub | Errata and corrections to the content | when I see it |

The email address is in [`/.well-known/security.txt`](/.well-known/security.txt) and in
the footer. I do not put it in plain text here, for the obvious reason.

::: tip title="Before you write"
If your message is *"can you teach me to hack?"*, the answer is in the
[Arsenal](/en/arsenal/): that is the list of resources I started with, which is exactly
what I would reply.
:::

## PGP

Encrypt anything containing details of an unpublished vulnerability, client data, or
information you would not want to see forwarded.

::: terminal title="czrxplo1t@lab"
czrxplo1t@lab:~$ curl -s https://Czr-Xploit.github.io/static/pgp/czrxplo1t.asc | gpg --import
gpg: key 0000000000000000: public key "CzrXplo1t" imported
gpg: Total number processed: 1
gpg:               imported: 1
czrxplo1t@lab:~$ gpg --fingerprint CzrXplo1t
:::

::: warning title="Verify the fingerprint"
Downloading a key from the same site that claims it proves nothing on its own: whoever
controls the site controls the key. Check the fingerprint through a second,
independent channel before trusting it for anything serious.
:::

<!-- TODO CzrXplo1t: publish the key at theme/static/pgp/czrxplo1t.asc and put the real fingerprint in site.json -->

## Responsible disclosure

If you have found something on this site:

- [x] Write to me through `security.txt` with reproduction steps.
- [x] Give me 72 hours to acknowledge receipt.
- [ ] You do not need to wait 90 days: this is a personal static site, not a product.

I will credit you under whatever name you give me, or not credit you at all if you
prefer that. What I will not do is publish your report without telling you first.

## What I do not do

- No unauthorised testing against third parties, not even "to prove a point".
- No sharing of client material, anonymised or otherwise.
- No signing an NDA to read a report you want me to review for free.
