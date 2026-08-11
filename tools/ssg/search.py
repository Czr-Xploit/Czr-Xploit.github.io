"""
Client-side search index construction.

The whole index ships as one JSON file per language and is fetched lazily the
first time the reader opens search or the command palette.  That keeps it off
the critical path entirely: a visitor who never searches never downloads it.

The index is deliberately dumb -- documents with a truncated plain-text body
and a small inverted index of term -> document ids.  Ranking happens in the
browser.  There is no stemmer and no stopword list beyond a short one per
language, because a security blog's vocabulary is full of tokens
(``LD_PRELOAD``, ``0x41414141``, ``--proxy-chain``) that any stemmer would
mangle and any generic stopword list would keep.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Iterable, Sequence

from .content import ArsenalEntry, Document
from .markdown import plain_text

__all__ = ["build_search_index", "build_command_index", "tokenize"]


# Keep tokens that a reader would actually type. Underscores, hyphens and dots
# stay inside a token so `LD_PRELOAD`, `x86-64` and `libc.so.6` survive intact.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]{1,40}|0x[0-9a-fA-F]+|[À-ɏ]+", re.UNICODE)

_STOPWORDS: dict[str, set[str]] = {
    "es": {
        "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las", "por", "un", "para",
        "con", "no", "una", "su", "al", "lo", "como", "mas", "más", "pero", "sus", "le", "ya", "o",
        "este", "esta", "esto", "son", "es", "the", "of", "to", "and", "in", "sobre", "entre",
        "cuando", "todo", "toda", "hay", "ser", "muy", "sin", "puede", "hace", "desde", "donde",
    },
    "en": {
        "the", "of", "to", "and", "in", "a", "is", "that", "it", "for", "on", "with", "as", "was",
        "at", "by", "an", "be", "this", "which", "or", "from", "but", "not", "are", "we", "you",
        "can", "has", "have", "will", "if", "when", "how", "what", "all", "its", "into", "than",
    },
}

_MAX_BODY_CHARS = 1600
_MIN_TOKEN_LENGTH = 2


def tokenize(text: str, lang: str = "es") -> list[str]:
    """Lowercase tokens, stopwords removed, order preserved."""
    stop = _STOPWORDS.get(lang, set())
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        token = match.group().lower().strip("./-_")
        if len(token) < _MIN_TOKEN_LENGTH or token in stop:
            continue
        if token.isdigit() and len(token) < 4:
            continue
        tokens.append(token)
    return tokens


def _term_frequencies(tokens: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for token in tokens:
        counts[token] += 1
    return dict(counts)


def build_search_index(
    config,
    documents: Sequence[Document],
    arsenal: Sequence[ArsenalEntry],
    *,
    lang: str,
) -> str:
    """Return the JSON payload for ``/search-<lang>.json``."""
    records: list[dict[str, Any]] = []
    postings: dict[str, list[list[int]]] = defaultdict(list)

    for index, document in enumerate(documents):
        body = plain_text(document.rendered.html)
        record = {
            "i": index,
            "t": document.title,
            "u": document.url,
            "s": document.summary[:220],
            "k": document.kind,
            "d": document.date.isoformat(),
            "g": document.tags[:10],
            "r": document.reading_minutes,
            "x": body[:_MAX_BODY_CHARS],
        }
        if document.platform:
            record["p"] = document.platform
        if document.difficulty:
            record["f"] = document.difficulty
        records.append(record)

        # Weighted: title and tags count for more than body prose.
        weighted: list[str] = []
        weighted.extend(tokenize(document.title, lang) * 6)
        weighted.extend(tokenize(" ".join(document.tags), lang) * 4)
        weighted.extend(tokenize(document.summary, lang) * 2)
        weighted.extend(tokenize(body[: _MAX_BODY_CHARS * 3], lang))
        for term, count in _term_frequencies(weighted).items():
            postings[term].append([index, min(count, 255)])

    offset = len(records)
    for position, entry in enumerate(arsenal):
        summary = entry.summary_for(lang)
        record = {
            "i": offset + position,
            "t": entry.name,
            "u": config.language(lang).url_for("arsenal") + f"#tool-{entry.slug}",
            "s": summary[:220],
            "k": "tool",
            "d": "",
            "g": entry.tags[:10],
            "r": 0,
            "x": plain_text(entry.notes_for(lang))[:600],
        }
        records.append(record)
        weighted = (
            tokenize(entry.name, lang) * 6
            + tokenize(" ".join(entry.tags + [entry.category]), lang) * 4
            + tokenize(summary, lang)
        )
        for term, count in _term_frequencies(weighted).items():
            postings[term].append([offset + position, min(count, 255)])

    # Drop terms that match nearly everything: they cost bytes and rank nothing.
    threshold = max(4, int(len(records) * 0.85))
    trimmed = {
        term: sorted(entries, key=lambda pair: -pair[1])[:60]
        for term, entries in postings.items()
        if len(entries) <= threshold
    }

    payload = {
        "v": 2,
        "lang": lang,
        "count": len(records),
        "docs": records,
        "terms": dict(sorted(trimmed.items())),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def build_command_index(config, library, *, lang: str) -> str:
    """The virtual filesystem the in-page terminal walks.

    Shipping this as data rather than hard-coding paths in JavaScript means the
    terminal's ``ls`` and ``cat`` always reflect what was actually published.
    """
    language = config.language(lang)
    tree: dict[str, Any] = {
        "lang": lang,
        "root": language.url_for(),
        "dirs": {},
        "themes": config.themes,
        "langs": [
            {"code": entry.code, "url": entry.url_for(), "name": entry.native_name}
            for entry in config.languages
        ],
    }

    def node(document: Document) -> dict[str, Any]:
        return {
            "name": f"{document.slug}.md",
            "title": document.title,
            "url": document.url,
            "date": document.date.isoformat(),
            "size": max(1, document.rendered.word_count),
            "tags": document.tags[:6],
            "summary": document.summary[:200],
        }

    tree["dirs"]["blog"] = [node(document) for document in library.posts(lang)]
    tree["dirs"]["writeups"] = [node(document) for document in library.writeups(lang)]
    tree["dirs"]["arsenal"] = [
        {
            "name": f"{entry.slug}",
            "title": entry.name,
            "url": language.url_for("arsenal") + f"#tool-{entry.slug}",
            "date": "",
            "size": 1,
            "tags": entry.tags[:6],
            "summary": entry.summary_for(lang)[:200],
        }
        for entry in library.arsenal
    ]
    tree["dirs"]["pages"] = [node(document) for document in library.pages(lang)]
    tree["stats"] = library.stats(lang)
    return json.dumps(tree, ensure_ascii=False, separators=(",", ":")) + "\n"
