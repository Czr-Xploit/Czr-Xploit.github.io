"""
Content loading: frontmatter parsing, the Document model, and collections.

The frontmatter dialect is a deliberately small subset of YAML.  It covers
scalars, ISO dates, booleans, inline and block lists, one level of nested
mapping, and block scalars (``|`` and ``>``).  It does not cover anchors,
aliases, tags, flow mappings or multi-document streams -- if a post needs any
of those, the post is wrong, not the parser.

Refusing to depend on PyYAML is not stubbornness for its own sake: a security
blog that shells out to a third-party deserialiser at build time is making a
joke at its own expense.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from .markdown import Markdown, MarkdownResult, plain_text, slugify

__all__ = [
    "Document",
    "ArsenalEntry",
    "ContentError",
    "parse_frontmatter",
    "load_documents",
    "load_arsenal",
    "Library",
]


class ContentError(Exception):
    """Raised when a source file cannot be turned into a Document."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)")
_KEY_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z_][\w.\-]*)[ \t]*:(?P<rest>.*)$")
_LIST_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)-[ \t]*(?P<value>.*)$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:?\d{2})?$")

_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}
_NULL = {"", "null", "~", "none"}


def _coerce_scalar(raw: str) -> Any:
    value = raw.strip()

    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        return inner

    lowered = value.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    if lowered in _NULL:
        return None

    if _ISO_DATE_RE.match(value):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return value
    if _ISO_DATETIME_RE.match(value):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value

    if re.fullmatch(r"[-+]?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(r"[-+]?\d*\.\d+(?:[eE][-+]?\d+)?", value):
        try:
            return float(value)
        except ValueError:
            return value

    if value.startswith("[") and value.endswith("]"):
        return _split_inline_list(value[1:-1])

    return value


def _split_inline_list(body: str) -> list[Any]:
    items: list[Any] = []
    current: list[str] = []
    quote: str | None = None
    depth = 0
    for char in body:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        if char == "," and depth == 0:
            items.append(_coerce_scalar("".join(current)))
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        items.append(_coerce_scalar(tail))
    return [item for item in items if item is not None or item is False]


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def parse_frontmatter(source: str) -> tuple[dict[str, Any], str]:
    """Split ``source`` into (metadata, body).

    Returns an empty mapping when the file has no frontmatter block.
    """
    match = _FRONTMATTER_RE.match(source.replace("\r\n", "\n"))
    if match is None:
        return {}, source
    body = source[match.end():]
    return _parse_block(match.group("body").split("\n")), body


def _parse_block(lines: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    index = 0
    total = len(lines)

    while index < total:
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue

        key_match = _KEY_RE.match(line)
        if key_match is None:
            index += 1
            continue

        key = key_match.group("key")
        rest = key_match.group("rest").strip()
        base_indent = _indent_of(line)

        # Block scalar: key: | or key: >
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            fold = rest[0] == ">"
            chomp = "-" in rest
            collected: list[str] = []
            index += 1
            while index < total:
                candidate = lines[index]
                if candidate.strip() and _indent_of(candidate) <= base_indent:
                    break
                collected.append(candidate[base_indent + 2:] if len(candidate) > base_indent + 2 else candidate.strip())
                index += 1
            text = (" ".join(part.strip() for part in collected) if fold else "\n".join(collected))
            data[key] = text.strip() if chomp else text.rstrip() + ("" if fold else "\n")
            continue

        # Inline value on the same line.
        if rest and not rest.startswith("#"):
            data[key] = _coerce_scalar(rest)
            index += 1
            continue

        # Nothing on the line: look ahead for a block list or a nested mapping.
        lookahead = index + 1
        while lookahead < total and not lines[lookahead].strip():
            lookahead += 1
        if lookahead >= total:
            data[key] = None
            index = lookahead
            continue

        child = lines[lookahead]
        child_indent = _indent_of(child)
        if child_indent <= base_indent:
            data[key] = None
            index += 1
            continue

        if _LIST_ITEM_RE.match(child):
            items: list[Any] = []
            index = lookahead
            while index < total:
                candidate = lines[index]
                if not candidate.strip():
                    index += 1
                    continue
                if _indent_of(candidate) <= base_indent:
                    break
                item_match = _LIST_ITEM_RE.match(candidate)
                if item_match is None:
                    break
                items.append(_coerce_scalar(item_match.group("value")))
                index += 1
            data[key] = items
            continue

        nested: list[str] = []
        index = lookahead
        while index < total:
            candidate = lines[index]
            if candidate.strip() and _indent_of(candidate) <= base_indent:
                break
            nested.append(candidate[child_indent:] if len(candidate) >= child_indent else candidate)
            index += 1
        data[key] = _parse_block(nested)

    return data


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #

VALID_KINDS = {"post", "writeup", "page"}

_KIND_BY_DIR = {
    "posts": "post",
    "writeups": "writeup",
    "pages": "page",
}

_SECTION_SEGMENT = {
    "post": {"es": "blog", "en": "blog"},
    "writeup": {"es": "writeups", "en": "writeups"},
    "page": {"es": "", "en": ""},
}


@dataclass
class Document:
    # provenance
    source_path: str
    kind: str
    lang: str

    # identity
    slug: str
    translation_key: str
    title: str

    # dates
    date: dt.date
    updated: dt.date | None = None

    # descriptive
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    cover: str = ""
    cover_gif: str = ""
    cover_alt: str = ""

    # flags
    draft: bool = False
    featured: bool = False
    pinned: bool = False
    toc: bool = True

    # writeup / research extras
    platform: str = ""
    difficulty: str = ""
    os_name: str = ""
    techniques: list[str] = field(default_factory=list)
    cve: list[str] = field(default_factory=list)
    severity: str = ""
    disclosure_status: str = ""
    canonical: str = ""

    # content
    body: str = ""
    rendered: MarkdownResult = field(default_factory=MarkdownResult)
    raw_meta: dict[str, Any] = field(default_factory=dict)

    # computed at load time
    url: str = ""
    output_path: str = ""
    reading_minutes: int = 1

    # wired up after the whole library is loaded
    translations: dict[str, "Document"] = field(default_factory=dict, repr=False)
    previous: "Document | None" = field(default=None, repr=False)
    next: "Document | None" = field(default=None, repr=False)
    related: list["Document"] = field(default_factory=list, repr=False)

    # -- convenience for templates ---------------------------------------- #

    @property
    def html(self) -> str:
        return self.rendered.html

    @property
    def toc_entries(self) -> list[dict[str, Any]]:
        return self.rendered.toc

    @property
    def word_count(self) -> int:
        return self.rendered.word_count

    @property
    def is_writeup(self) -> bool:
        return self.kind == "writeup"

    @property
    def year(self) -> str:
        return self.date.strftime("%Y")

    @property
    def iso_date(self) -> str:
        return self.date.isoformat()

    @property
    def has_media(self) -> bool:
        return bool(self.cover or self.cover_gif or self.rendered.media)

    def translation(self, lang: str) -> "Document | None":
        return self.translations.get(lang)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "lang": self.lang,
            "kind": self.kind,
            "slug": self.slug,
            "date": self.date.isoformat(),
            "summary": self.summary,
            "tags": self.tags,
            "featured": self.featured,
            "reading": self.reading_minutes,
        }

    def search_record(self) -> dict[str, Any]:
        """The shape the client-side index consumes. Kept small on purpose."""
        return {
            "t": self.title,
            "u": self.url,
            "s": self.summary,
            "k": self.kind,
            "l": self.lang,
            "d": self.date.isoformat(),
            "g": self.tags,
            "b": plain_text(self.rendered.html)[:1400],
            "r": self.reading_minutes,
        }


@dataclass
class ArsenalEntry:
    """A tool or resource in the Arsenal section.

    Bilingual by field rather than by file: entries are one paragraph long, and
    splitting them across two files would double the maintenance for no gain.
    """

    slug: str
    name: str
    url: str
    category: str
    tags: list[str] = field(default_factory=list)
    summary: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    license: str = ""
    language: str = ""
    featured: bool = False
    source_path: str = ""

    def summary_for(self, lang: str) -> str:
        return self.summary.get(lang) or self.summary.get("es") or self.summary.get("en") or ""

    def notes_for(self, lang: str) -> str:
        return self.notes.get(lang) or self.notes.get("es") or self.notes.get("en") or ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "url": self.url,
            "category": self.category,
            "tags": self.tags,
            "featured": self.featured,
        }


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
    return [str(value)]


def _as_date(value: Any, path: str, key: str, *, required: bool = True) -> dt.date | None:
    if value is None or value == "":
        if required:
            raise ContentError(path, f"missing required frontmatter field {key!r}")
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError as error:
            raise ContentError(path, f"{key} is not an ISO date (YYYY-MM-DD): {value!r}") from error
    raise ContentError(path, f"{key} has an unusable type: {type(value).__name__}")


def normalise_tag(tag: str) -> str:
    """Tags are compared case- and accent-insensitively but displayed as typed."""
    folded = unicodedata.normalize("NFKD", tag)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def load_document(path: str, *, config, kind: str, lang: str) -> Document:
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()

    meta, body = parse_frontmatter(source)
    if not meta:
        raise ContentError(path, "no frontmatter block found (expected a leading '---' fence)")

    title = str(meta.get("title") or "").strip()
    if not title:
        raise ContentError(path, "frontmatter field 'title' is required and must not be empty")

    file_stem = os.path.splitext(os.path.basename(path))[0]
    slug = slugify(str(meta.get("slug") or file_stem))
    date = _as_date(meta.get("date"), path, "date")
    assert date is not None

    declared_lang = str(meta.get("lang") or lang).strip()
    if declared_lang != lang:
        raise ContentError(
            path,
            f"frontmatter says lang={declared_lang!r} but the file lives in the {lang!r} tree",
        )

    translation_key = str(meta.get("translation_key") or meta.get("key") or file_stem).strip()

    language = config.language(lang)
    section = _SECTION_SEGMENT.get(kind, {}).get(lang, "")
    url = language.url_for(section, slug) if section else language.url_for(slug)

    renderer = Markdown(lang=lang, base_url=config.base_url)
    rendered = renderer.convert(body)

    summary = str(meta.get("summary") or meta.get("description") or "").strip()
    if not summary:
        summary = rendered.excerpt

    words = rendered.word_count
    reading = max(1, round(words / max(60, config.words_per_minute)))

    document = Document(
        source_path=path,
        kind=kind,
        lang=lang,
        slug=slug,
        translation_key=translation_key,
        title=title,
        date=date,
        updated=_as_date(meta.get("updated"), path, "updated", required=False),
        summary=summary,
        tags=_as_list(meta.get("tags")),
        cover=str(meta.get("cover") or ""),
        cover_gif=str(meta.get("cover_gif") or ""),
        cover_alt=str(meta.get("cover_alt") or ""),
        draft=bool(meta.get("draft", False)),
        featured=bool(meta.get("featured", False)),
        pinned=bool(meta.get("pinned", False)),
        toc=bool(meta.get("toc", True)),
        platform=str(meta.get("platform") or ""),
        difficulty=str(meta.get("difficulty") or ""),
        os_name=str(meta.get("os") or ""),
        techniques=_as_list(meta.get("techniques")),
        cve=_as_list(meta.get("cve")),
        severity=str(meta.get("severity") or ""),
        disclosure_status=str(meta.get("disclosure_status") or ""),
        canonical=str(meta.get("canonical") or ""),
        body=body,
        rendered=rendered,
        raw_meta=meta,
        url=url,
        output_path=os.path.join(url.strip("/"), "index.html") if url != "/" else "index.html",
        reading_minutes=reading,
    )
    return document


def _iter_markdown(root: str) -> Iterator[str]:
    if not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith(".") or filename.startswith("_"):
                continue
            if filename.endswith((".md", ".markdown")):
                yield os.path.join(dirpath, filename)


def load_documents(config, *, include_drafts: bool = False) -> list[Document]:
    """Walk ``content/`` and build every Document the site publishes."""
    documents: list[Document] = []
    errors: list[str] = []

    for directory, kind in _KIND_BY_DIR.items():
        for language in config.languages:
            root = os.path.join(config.content_path, directory, language.code)
            for path in _iter_markdown(root):
                try:
                    document = load_document(path, config=config, kind=kind, lang=language.code)
                except ContentError as error:
                    errors.append(str(error))
                    continue
                if document.draft and not include_drafts:
                    continue
                documents.append(document)

    if errors:
        raise ContentError("content", "\n  - " + "\n  - ".join(errors))

    _check_unique_urls(documents)
    return documents


def _check_unique_urls(documents: Iterable[Document]) -> None:
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for document in documents:
        if document.url in seen:
            clashes.append(f"{document.url} <- {seen[document.url]} and {document.source_path}")
        seen[document.url] = document.source_path
    if clashes:
        raise ContentError("content", "duplicate output URLs:\n  - " + "\n  - ".join(clashes))


_ARSENAL_SPLIT_RE = re.compile(r"^<!--\s*(?P<lang>[a-z]{2})\s*-->\s*$", re.MULTILINE)


def load_arsenal(config) -> list[ArsenalEntry]:
    """Load ``content/arsenal/*.md``.

    Body text may be split per language with ``<!-- es -->`` / ``<!-- en -->``
    markers; without markers the whole body is used for every language.
    """
    root = os.path.join(config.content_path, "arsenal")
    entries: list[ArsenalEntry] = []
    codes = config.language_codes

    for path in _iter_markdown(root):
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        meta, body = parse_frontmatter(source)
        if not meta:
            raise ContentError(path, "arsenal entries need a frontmatter block")

        name = str(meta.get("name") or meta.get("title") or "").strip()
        if not name:
            raise ContentError(path, "arsenal entry requires 'name'")

        summary: dict[str, str] = {}
        for code in codes:
            value = meta.get(f"summary_{code}") or (meta.get("summary") if code == config.default_language else "")
            summary[code] = str(value or "").strip()

        notes: dict[str, str] = {}
        segments = _ARSENAL_SPLIT_RE.split(body)
        if len(segments) > 1:
            # split() yields [pre, lang, text, lang, text, ...]
            for index in range(1, len(segments) - 1, 2):
                code = segments[index]
                text = segments[index + 1]
                if code in codes:
                    notes[code] = Markdown(lang=code).convert(text).html
        elif body.strip():
            for code in codes:
                notes[code] = Markdown(lang=code).convert(body).html

        entries.append(
            ArsenalEntry(
                slug=slugify(str(meta.get("slug") or name)),
                name=name,
                url=str(meta.get("url") or ""),
                category=str(meta.get("category") or "misc").strip().lower(),
                tags=_as_list(meta.get("tags")),
                summary=summary,
                notes=notes,
                license=str(meta.get("license") or ""),
                language=str(meta.get("language") or ""),
                featured=bool(meta.get("featured", False)),
                source_path=path,
            )
        )

    entries.sort(key=lambda entry: (entry.category, entry.name.lower()))
    return entries


# --------------------------------------------------------------------------- #
# Library: the whole content set with its cross-references resolved
# --------------------------------------------------------------------------- #

@dataclass
class TagInfo:
    name: str
    key: str
    count: int
    documents: list[Document] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "key": self.key, "count": self.count}


class Library:
    """Everything the templates need, indexed the ways they need it."""

    def __init__(self, config, documents: list[Document], arsenal: list[ArsenalEntry]) -> None:
        self.config = config
        self.documents = documents
        self.arsenal = arsenal
        self._link_translations()
        self._sort_and_chain()
        self._build_tag_index()
        self._compute_related()

    # -- construction ----------------------------------------------------- #

    def _link_translations(self) -> None:
        by_key: dict[tuple[str, str], list[Document]] = {}
        for document in self.documents:
            by_key.setdefault((document.kind, document.translation_key), []).append(document)
        for group in by_key.values():
            for document in group:
                for sibling in group:
                    if sibling.lang != document.lang:
                        document.translations[sibling.lang] = sibling

    def _sort_and_chain(self) -> None:
        self.documents.sort(key=lambda doc: (doc.date, doc.slug), reverse=True)
        for lang in self.config.language_codes:
            for kind in ("post", "writeup"):
                series = [doc for doc in self.documents if doc.lang == lang and doc.kind == kind]
                for index, document in enumerate(series):
                    document.next = series[index - 1] if index > 0 else None
                    document.previous = series[index + 1] if index + 1 < len(series) else None

    def _build_tag_index(self) -> None:
        self.tags: dict[str, dict[str, TagInfo]] = {code: {} for code in self.config.language_codes}
        for document in self.documents:
            if document.kind == "page":
                continue
            for tag in document.tags:
                key = normalise_tag(tag)
                if not key:
                    continue
                bucket = self.tags[document.lang]
                info = bucket.get(key)
                if info is None:
                    info = TagInfo(name=tag, key=key, count=0)
                    bucket[key] = info
                info.count += 1
                info.documents.append(document)

    def _compute_related(self, *, limit: int = 3) -> None:
        """Rank siblings by shared tags, then recency. No vectors, no magic."""
        for document in self.documents:
            if document.kind == "page":
                continue
            own = {normalise_tag(tag) for tag in document.tags}
            scored: list[tuple[int, dt.date, Document]] = []
            for candidate in self.documents:
                if candidate is document or candidate.lang != document.lang or candidate.kind == "page":
                    continue
                overlap = len(own & {normalise_tag(tag) for tag in candidate.tags})
                if candidate.kind == document.kind:
                    overlap += 1
                if overlap:
                    scored.append((overlap, candidate.date, candidate))
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            document.related = [item[2] for item in scored[:limit]]

    # -- queries ---------------------------------------------------------- #

    def by_lang(self, lang: str, *, kind: str | None = None) -> list[Document]:
        return [
            document
            for document in self.documents
            if document.lang == lang and (kind is None or document.kind == kind)
        ]

    def posts(self, lang: str) -> list[Document]:
        return self.by_lang(lang, kind="post")

    def writeups(self, lang: str) -> list[Document]:
        return self.by_lang(lang, kind="writeup")

    def pages(self, lang: str) -> list[Document]:
        return self.by_lang(lang, kind="page")

    def feed_items(self, lang: str) -> list[Document]:
        items = [doc for doc in self.by_lang(lang) if doc.kind in ("post", "writeup")]
        return items[: self.config.feed_items]

    def latest(self, lang: str, count: int = 6) -> list[Document]:
        items = [doc for doc in self.by_lang(lang) if doc.kind in ("post", "writeup")]
        pinned = [doc for doc in items if doc.pinned]
        rest = [doc for doc in items if not doc.pinned]
        return (pinned + rest)[:count]

    def featured(self, lang: str, count: int = 3) -> list[Document]:
        items = [doc for doc in self.by_lang(lang) if doc.featured and doc.kind != "page"]
        return items[:count]

    def tag_list(self, lang: str, *, minimum: int = 1) -> list[TagInfo]:
        return sorted(
            (info for info in self.tags.get(lang, {}).values() if info.count >= minimum),
            key=lambda info: (-info.count, info.key),
        )

    def arsenal_categories(self) -> list[str]:
        return sorted({entry.category for entry in self.arsenal})

    def stats(self, lang: str) -> dict[str, int]:
        items = self.by_lang(lang)
        return {
            "posts": len([doc for doc in items if doc.kind == "post"]),
            "writeups": len([doc for doc in items if doc.kind == "writeup"]),
            "tools": len(self.arsenal),
            "tags": len(self.tags.get(lang, {})),
            "words": sum(doc.word_count for doc in items),
        }
