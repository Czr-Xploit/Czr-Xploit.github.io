"""
Allowlist HTML sanitiser built on ``html.parser``.

Rationale
---------
Article sources are authored by the site owner, so this is not the primary
trust boundary.  It exists anyway because the cost of being wrong on a
security blog is reputational, and because content can arrive from places the
author does not fully control: a pull request, a snippet pasted from a report,
a translation returned by a tool.  Everything that is not explicitly permitted
is dropped, and the parser never reconstructs markup it did not understand.

Design notes
------------
* Deny by default.  Unknown tags are removed but their text is preserved.
* Attributes are filtered per-tag; there is no global "allow anything" tag.
* URL-bearing attributes go through a scheme check that rejects ``javascript:``,
  ``data:`` (except a narrow image allowlist), ``vbscript:`` and friends, after
  first decoding HTML entities and stripping control characters so that
  ``java\\x00script:`` and ``&#106;avascript:`` cannot slip past.
* ``style`` attributes are refused entirely rather than parsed; anything that
  needs styling gets a class.
* Comments, processing instructions, declarations and CDATA are dropped.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Iterable

__all__ = ["sanitize_html", "Sanitizer", "ALLOWED_TAGS", "ALLOWED_ATTRIBUTES"]


# Tags whose content is structural markup we are happy to emit verbatim.
ALLOWED_TAGS: dict[str, set[str]] = {
    # sectioning / flow
    "div": {"class", "id", "role", "lang", "dir"},
    "section": {"class", "id", "aria-label", "aria-labelledby"},
    "article": {"class", "id"},
    "aside": {"class", "id", "aria-label"},
    "header": {"class", "id"},
    "footer": {"class", "id"},
    "nav": {"class", "id", "aria-label"},
    "main": {"class", "id"},
    "p": {"class", "id", "dir"},
    "br": set(),
    "hr": {"class"},
    "blockquote": {"class", "cite"},
    "pre": {"class", "data-lang", "data-title", "tabindex", "role", "aria-label"},
    "code": {"class"},
    "samp": {"class"},
    "kbd": {"class"},
    "var": {"class"},
    "figure": {"class", "id"},
    "figcaption": {"class"},
    "details": {"class", "open", "id"},
    "summary": {"class"},
    "hgroup": {"class"},
    # headings
    "h1": {"class", "id"},
    "h2": {"class", "id"},
    "h3": {"class", "id"},
    "h4": {"class", "id"},
    "h5": {"class", "id"},
    "h6": {"class", "id"},
    # inline
    "a": {"class", "id", "href", "title", "rel", "target", "hreflang", "download", "aria-label"},
    "em": {"class"},
    "strong": {"class"},
    "b": {"class"},
    "i": {"class"},
    "u": {"class"},
    "s": {"class"},
    "del": {"class", "datetime"},
    "ins": {"class", "datetime"},
    "mark": {"class"},
    "small": {"class"},
    "sub": {"class"},
    "sup": {"class", "id"},
    "abbr": {"class", "title"},
    "cite": {"class"},
    "q": {"class", "cite"},
    "time": {"class", "datetime"},
    "span": {"class", "id", "lang", "dir", "title", "aria-hidden", "aria-label", "data-text"},
    "wbr": set(),
    "bdi": {"class"},
    "bdo": {"class", "dir"},
    # lists
    "ul": {"class", "id"},
    "ol": {"class", "id", "start", "reversed", "type"},
    "li": {"class", "id", "value"},
    "dl": {"class"},
    "dt": {"class"},
    "dd": {"class"},
    # tables
    "table": {"class", "id"},
    "thead": {"class"},
    "tbody": {"class"},
    "tfoot": {"class"},
    "tr": {"class"},
    "th": {"class", "colspan", "rowspan", "scope", "abbr"},
    "td": {"class", "colspan", "rowspan", "headers"},
    "caption": {"class"},
    "colgroup": {"class", "span"},
    "col": {"class", "span"},
    # media
    "img": {
        "class", "id", "src", "alt", "title", "width", "height",
        "loading", "decoding", "fetchpriority", "sizes", "srcset",
    },
    "picture": {"class"},
    "source": {"class", "src", "srcset", "type", "media", "sizes", "width", "height"},
    "video": {
        "class", "id", "src", "poster", "width", "height", "controls",
        "autoplay", "loop", "muted", "playsinline", "preload", "aria-label",
    },
    "audio": {"class", "id", "src", "controls", "preload", "loop", "muted"},
    "track": {"src", "kind", "srclang", "label", "default"},
    # forms - only the read-only, no-JS-needed subset used by the theme
    "button": {"class", "id", "type", "aria-label", "aria-expanded", "aria-controls", "data-action", "data-value", "title", "disabled"},
    "label": {"class", "for"},
    "progress": {"class", "value", "max", "aria-label"},
    "meter": {"class", "value", "min", "max", "low", "high", "optimum"},
    # inline vector graphics used by the theme's icons
    "svg": {"class", "width", "height", "viewbox", "viewBox", "fill", "stroke", "aria-hidden", "role", "focusable", "xmlns", "stroke-width", "stroke-linecap", "stroke-linejoin"},
    "path": {"d", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "fill-rule", "clip-rule", "opacity"},
    "circle": {"cx", "cy", "r", "fill", "stroke", "stroke-width", "opacity"},
    "rect": {"x", "y", "width", "height", "rx", "ry", "fill", "stroke", "stroke-width", "opacity"},
    "line": {"x1", "y1", "x2", "y2", "stroke", "stroke-width", "stroke-linecap"},
    "polyline": {"points", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"},
    "polygon": {"points", "fill", "stroke", "stroke-width"},
    "g": {"class", "fill", "stroke", "stroke-width", "opacity", "transform"},
    "title": {"id"},
    "desc": {"id"},
    "use": {"href", "x", "y", "width", "height"},
}

# Void elements that must be serialised self-closing.
VOID_TAGS = {"br", "hr", "img", "source", "track", "wbr", "col", "use"}

# Attributes whose value is a URL and therefore needs scheme validation.
URL_ATTRIBUTES = {"href", "src", "poster", "cite", "srcset", "download", "use"}

# Attribute names that are never allowed regardless of tag.
FORBIDDEN_ATTRIBUTE_RE = re.compile(r"^(on|xlink:|xml:|form)", re.IGNORECASE)

SAFE_SCHEMES = {"http", "https", "mailto", "ftp", "ftps", "irc", "ircs", "matrix", "xmpp", "magnet", "gemini", "news", "tel"}

# Only these data: payloads are permitted, and only in image positions.
SAFE_DATA_PREFIXES = (
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/gif;base64,",
    "data:image/webp;base64,",
    "data:image/avif;base64,",
    "data:image/svg+xml;base64,",
)

_CONTROL_CHARS = re.compile(r"[\x00-\x20\x7f  -‏ - ﻿]")
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_CLASS_RE = re.compile(r"^[A-Za-z0-9 _\-:/\[\]().]{0,400}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,120}$")

ALLOWED_ATTRIBUTES = ALLOWED_TAGS  # convenient alias for callers


def _normalise_url(value: str) -> str:
    """Collapse the tricks used to smuggle a scheme past a naive check."""
    decoded = html.unescape(value or "")
    # Repeat once: entity encoding is sometimes doubled.
    decoded = html.unescape(decoded)
    return _CONTROL_CHARS.sub("", decoded).strip()


def is_safe_url(value: str, *, allow_data_images: bool = False) -> bool:
    """Return True when ``value`` is a URL we are willing to emit."""
    candidate = _normalise_url(value)
    if not candidate:
        return False
    lowered = candidate.lower()

    if lowered.startswith("data:"):
        return allow_data_images and any(lowered.startswith(prefix) for prefix in SAFE_DATA_PREFIXES)

    match = _SCHEME_RE.match(candidate)
    if match is None:
        # Relative, root-relative, protocol-relative or fragment.
        if candidate.startswith("//"):
            # Protocol-relative loads a third-party origin; the site forbids it.
            return False
        return True
    return match.group(1).lower() in SAFE_SCHEMES


def _safe_srcset(value: str) -> str | None:
    """Validate every candidate in a ``srcset`` list."""
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        return None
    for part in parts:
        url = part.split()[0]
        if not is_safe_url(url, allow_data_images=True):
            return None
    return ", ".join(parts)


class Sanitizer(HTMLParser):
    """Rewrites an HTML fragment, keeping only allowlisted markup."""

    def __init__(
        self,
        *,
        allowed_tags: dict[str, set[str]] | None = None,
        drop_content_of: Iterable[str] = ("script", "style", "iframe", "object", "embed", "template", "noscript", "form", "input", "select", "textarea", "link", "meta", "base"),
        external_link_rel: str = "noopener noreferrer",
    ) -> None:
        super().__init__(convert_charrefs=False)
        self.allowed = allowed_tags if allowed_tags is not None else ALLOWED_TAGS
        self.drop_content_of = set(drop_content_of)
        self.external_link_rel = external_link_rel
        self.out: list[str] = []
        self.open_tags: list[str] = []
        self._suppress_depth = 0
        self._suppressing: str | None = None

    # -- helpers ---------------------------------------------------------- #

    def _emit(self, text: str) -> None:
        if self._suppress_depth == 0:
            self.out.append(text)

    def _filter_attributes(self, tag: str, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
        permitted = self.allowed.get(tag, set())
        kept: list[tuple[str, str]] = []
        seen: set[str] = set()

        for raw_name, raw_value in attrs:
            name = (raw_name or "").strip().lower()
            if not name or name in seen:
                continue
            if FORBIDDEN_ATTRIBUTE_RE.match(name):
                continue
            if name == "style":
                continue
            # viewBox arrives lowercased from the parser; accept either spelling.
            canonical = "viewBox" if name == "viewbox" else name
            if name not in {attr.lower() for attr in permitted}:
                continue

            value = raw_value if raw_value is not None else ""
            value = html.unescape(value)

            if name in ("class",):
                if not _CLASS_RE.match(value):
                    continue
            elif name in ("id", "for", "headers", "aria-controls", "aria-labelledby"):
                if not _ID_RE.match(value):
                    continue
            elif name == "srcset":
                checked = _safe_srcset(value)
                if checked is None:
                    continue
                value = checked
            elif name in URL_ATTRIBUTES:
                if not is_safe_url(value, allow_data_images=tag in ("img", "source", "video")):
                    continue
                value = _normalise_url(value)
            elif name == "target":
                if value not in ("_blank", "_self"):
                    continue
            elif name in ("width", "height", "colspan", "rowspan", "span", "start", "value", "max", "min"):
                if not re.fullmatch(r"\d{1,6}(\.\d{1,3})?%?", value):
                    continue

            seen.add(name)
            kept.append((canonical, value))

        return self._postprocess_attributes(tag, kept)

    def _postprocess_attributes(self, tag: str, attrs: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Apply the invariants the theme depends on."""
        mapping = dict(attrs)

        if tag == "a":
            href = mapping.get("href", "")
            is_external = bool(_SCHEME_RE.match(href)) and not href.lower().startswith("mailto:")
            if mapping.get("target") == "_blank" or is_external:
                mapping.setdefault("target", "_blank")
                existing = set(mapping.get("rel", "").split())
                existing.update(self.external_link_rel.split())
                mapping["rel"] = " ".join(sorted(existing))
                classes = set(mapping.get("class", "").split())
                classes.add("ext")
                mapping["class"] = " ".join(sorted(classes))

        if tag == "img":
            mapping.setdefault("loading", "lazy")
            mapping.setdefault("decoding", "async")
            mapping.setdefault("alt", "")

        if tag in ("video", "audio"):
            mapping.pop("autoplay", None)  # autoplay is decided by the player module, never by content

        return list(mapping.items())

    @staticmethod
    def _serialise(tag: str, attrs: list[tuple[str, str]], *, self_closing: bool) -> str:
        parts = [tag]
        for name, value in attrs:
            if value == "" and name in ("controls", "loop", "muted", "playsinline", "open", "reversed", "default", "disabled"):
                parts.append(name)
                continue
            escaped = html.escape(value, quote=True).replace("'", "&#x27;")
            parts.append(f'{name}="{escaped}"')
        body = " ".join(parts)
        return f"<{body} />" if self_closing else f"<{body}>"

    # -- HTMLParser callbacks --------------------------------------------- #

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.drop_content_of:
            self._suppress_depth += 1
            if self._suppressing is None:
                self._suppressing = tag
            return
        if self._suppress_depth:
            return
        if tag not in self.allowed:
            return
        kept = self._filter_attributes(tag, attrs)
        if tag in VOID_TAGS:
            self.out.append(self._serialise(tag, kept, self_closing=True))
            return
        self.open_tags.append(tag)
        self.out.append(self._serialise(tag, kept, self_closing=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._suppress_depth or tag in self.drop_content_of or tag not in self.allowed:
            return
        kept = self._filter_attributes(tag, attrs)
        self.out.append(self._serialise(tag, kept, self_closing=True))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.drop_content_of:
            if self._suppress_depth:
                self._suppress_depth -= 1
                if self._suppress_depth == 0:
                    self._suppressing = None
            return
        if self._suppress_depth:
            return
        if tag in VOID_TAGS or tag not in self.allowed:
            return
        if tag not in self.open_tags:
            return
        # Close anything left dangling inside, so output is always well formed.
        while self.open_tags:
            current = self.open_tags.pop()
            self.out.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        self._emit(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        self._emit(html.escape(html.unescape(f"&{name};"), quote=False))

    def handle_charref(self, name: str) -> None:
        self._emit(html.escape(html.unescape(f"&#{name};"), quote=False))

    def handle_comment(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return

    def handle_pi(self, data: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    # -- public ----------------------------------------------------------- #

    def clean(self, fragment: str) -> str:
        self.out = []
        self.open_tags = []
        self._suppress_depth = 0
        self._suppressing = None
        self.feed(fragment)
        self.close()
        while self.open_tags:
            self.out.append(f"</{self.open_tags.pop()}>")
        return "".join(self.out)


def sanitize_html(fragment: str, **kwargs) -> str:
    """Convenience wrapper: sanitise a single fragment."""
    return Sanitizer(**kwargs).clean(fragment)
