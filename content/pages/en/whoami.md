---
title: whoami
slug: whoami
lang: en
translation_key: whoami
type: page
date: 2026-01-15
updated: 2026-08-11
summary: Who is behind this site, what gets published here, and under what rules.
tags: [meta]
toc: true
---

## $ id

I am **CzrXplo1t**. I work in offensive security: authorised assessments, vulnerability
analysis and reverse engineering. This site is the notebook where the things I learn
end up, when I think they are useful to someone else.

It is not a portfolio and not a shop window. It is a technical archive.

::: note title="On personal details"
I would rather the work spoke for itself, so you will not find my legal name, my
employer or a list of certifications here. If you need to verify my identity for a
formal process, write to me signed with PGP and we will sort it out privately.
:::

## $ cat ./what-gets-published

Three things, and nothing else:

1. **Research.** My own analysis: how something works underneath, where it breaks, and
   how to detect it. Written for someone who is going to reproduce it, not for someone
   who is going to cite it on LinkedIn.
2. **Writeups.** Training lab and machine walkthroughs. I include the dead ends,
   because a list of winning commands teaches nobody anything.
3. **Arsenal.** Tools and resources I actually use, with a note on why I reach for
   them over the obvious alternative.

What you will **not** find: sponsored content, news roundups, "top 10 tools" lists, or
anything generated without my having verified it.

## $ cat ./rules-of-engagement

This is the section I least enjoy writing and the most important one.

::: warning title="Authorised use only"
Every piece of technical material on this site is published for research, education
and defence. Applying any of it against systems you do not have **explicit written
authorisation** to test is, in most jurisdictions, a crime. The responsibility sits
entirely with whoever does it.
:::

My own rules, applied without exception:

- Anything I publish about a third party's system has been through coordinated
  disclosure first, or describes something already public.
- Training labs and practice machines are exactly that: environments built to be
  attacked. What I do there does not generalise.
- No screenshot, transcript or dump leaves here without going through redaction:
  internal hostnames, addresses, tokens, client data and image EXIF.
- If an article explains an attack, it also explains how to detect it and how to
  mitigate it. If I cannot write the second half, I do not publish the first.

## $ cat ./disclosure

I follow coordinated disclosure by default:

::: timeline title="Standard process"
- Day 0 — Contact the maintainer through their declared channel (security.txt, a bug bounty programme, or whatever public contact exists).
- Day 0–7 — Acknowledgement of receipt. If none arrives, a second attempt through an alternative route.
- Day 7–90 — Remediation window. I help with reproduction and patch verification if that is useful.
- Day 90 — Publication, coordinated with the maintainer if a dialogue is still going.
- No response after 90 days — Publication, with 14 days' notice.
:::

Timelines are negotiable when there is a real technical reason. They are not
negotiable when the reason is that publication would be awkward.

## $ cat ./this-site

Built with a custom static site generator written in Python, with **not a single
third-party dependency**. That decision is not an aesthetic one:

- There is no `npm install` pulling four hundred transitive packages into the
  publishing pipeline.
- There is no CDN, no remote fonts, no analytics, no trackers. Every byte your browser
  loads comes from this origin.
- The content security policy is strict and permits no inline scripts.
- It works completely with JavaScript disabled. The interactive parts are an addition,
  never a requirement.

::: tip title="Verifiable"
All of the site's code and the generator's code is published. If you do not believe any
of the above, it takes two minutes to check: read the source and open the network tab.
:::

## $ cat ./contact

Write to me encrypted whenever the content justifies it. The public key and
fingerprints are on the [contact page](/en/contact/).

To report something about this site specifically, the formal channel is
[`/.well-known/security.txt`](/.well-known/security.txt).

<!-- TODO CzrXplo1t: replace the PGP fingerprint in site.json and upload the key to theme/static/pgp/ -->
