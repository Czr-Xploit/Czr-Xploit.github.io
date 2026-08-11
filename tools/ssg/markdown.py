"""
Markdown parser for the CzrXplo1t blog.

Supports the CommonMark subset that technical writing actually uses, plus the
GitHub extensions (tables, task lists, strikethrough, autolinks, footnotes) and
a small set of custom container directives that give the theme its personality.

Not a CommonMark reference implementation, and not trying to be.  It is a
two-phase parser -- block structure first, inline markup second -- with a bias
towards predictable output over specification corner cases.  Anything it does
not recognise is escaped rather than passed through.

Extensions beyond CommonMark
----------------------------
``` fences        info string carries ``lang title="x.c" highlight="3,7-9" numbers``
tables            GFM pipe tables with alignment row
task lists        ``- [ ]`` / ``- [x]``
strikethrough     ``~~text~~``
highlight         ``==text==``
keys              ``++Ctrl+K++`` renders as <kbd>
footnotes         ``[^id]`` and ``[^id]: definition``
heading anchors   every heading gets a stable slug id and a permalink handle
containers        ``::: name key="value"`` ... ``:::``
                  note warning danger success tip terminal spoiler timeline
                  gif figure references columns
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .highlight import highlight_lines, resolve_language
from .sanitize import is_safe_url, sanitize_html

__all__ = ["Markdown", "MarkdownResult", "render_markdown", "slugify", "plain_text"]


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #

@dataclass
class Heading:
    level: int
    text: str
    slug: str

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "text": self.text, "slug": self.slug}


@dataclass
class MarkdownResult:
    html: str = ""
    headings: list[Heading] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    word_count: int = 0
    code_languages: list[str] = field(default_factory=list)
    has_math: bool = False
    excerpt: str = ""

    @property
    def toc(self) -> list[dict[str, Any]]:
        return [heading.as_dict() for heading in self.headings if 2 <= heading.level <= 4]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACE = re.compile(r"[-\s]+")


def slugify(text: str, *, max_length: int = 72) -> str:
    """ASCII-folding slug generator (handles Spanish accents and ñ)."""
    normalized = unicodedata.normalize("NFKD", text or "")
    folded = "".join(char for char in normalized if not unicodedata.combining(char))
    folded = folded.replace("ñ", "n").replace("Ñ", "N").replace("ø", "o").replace("ß", "ss")
    folded = _SLUG_STRIP.sub("", folded).strip().lower()
    slug = _SLUG_SPACE.sub("-", folded).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0] or slug[:max_length]
    return slug or "section"


_TAG_RE = re.compile(r"<[^>]+>")


def plain_text(markup: str) -> str:
    """Strip markup and collapse whitespace; used for excerpts and search."""
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", markup, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_attributes(source: str) -> dict[str, str]:
    """Parse ``key="value" key2=value2 flag`` into a dict (flags map to '')."""
    attributes: dict[str, str] = {}
    for match in re.finditer(r'([A-Za-z_][\w-]*)(?:=(?:"([^"]*)"|\'([^\']*)\'|([^\s]+)))?', source or ""):
        key = match.group(1)
        value = match.group(2)
        if value is None:
            value = match.group(3)
        if value is None:
            value = match.group(4)
        attributes[key] = value if value is not None else ""
    return attributes


def _parse_line_ranges(spec: str) -> set[int]:
    """``"3,7-9,12"`` -> {3,7,8,9,12}."""
    result: set[int] = set()
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, _, end = chunk.partition("-")
            try:
                result.update(range(int(start), int(end) + 1))
            except ValueError:
                continue
        else:
            try:
                result.add(int(chunk))
            except ValueError:
                continue
    return result


def _attr(value: str) -> str:
    return html.escape(value or "", quote=True).replace("'", "&#x27;")


# --------------------------------------------------------------------------- #
# Inline grammar
# --------------------------------------------------------------------------- #

_INLINE_PATTERN = re.compile(
    r"""
      (?P<escape>\\[\\`*_{}\[\]()#+\-.!|~<>:="'^])
    | (?P<code>(?P<fence>`+)(?P<codebody>[\s\S]+?)(?P=fence)(?!`))
    | (?P<autolink><(?P<autourl>(?:https?|ftp|mailto|matrix|xmpp|gemini):[^\s<>]+)>)
    | (?P<image>!\[(?P<alt>[^\]]*)\]\(\s*(?P<isrc><[^>]*>|[^\s)]+)(?:\s+(?P<ititle>"[^"]*"|'[^']*'))?\s*\))
    | (?P<link>\[(?P<ltext>(?:[^\[\]]|\[[^\[\]]*\])*)\]\(\s*(?P<lhref><[^>]*>|[^\s)]*)(?:\s+(?P<ltitle>"[^"]*"|'[^']*'))?\s*\))
    | (?P<footnote>\[\^(?P<fnid>[^\]\s]+)\])
    | (?P<refimage>!\[(?P<ralt>[^\]]*)\]\[(?P<rimgid>[^\]]*)\])
    | (?P<reflink>\[(?P<rtext>(?:[^\[\]]|\[[^\[\]]*\])*)\]\[(?P<refid>[^\]]*)\])
    | (?P<kbd>\+\+(?P<kbdbody>(?:[^+\n]|\+(?!\+)){1,60})\+\+)
    | (?P<strongem>\*\*\*(?=\S)(?P<sebody>[\s\S]+?)(?<=\S)\*\*\*)
    | (?P<strong>\*\*(?=\S)(?P<strongbody>[\s\S]+?)(?<=\S)\*\*)
    | (?P<strongu>(?<![\w])__(?=\S)(?P<strongubody>[\s\S]+?)(?<=\S)__(?![\w]))
    | (?P<em>\*(?=\S)(?P<embody>[^*\n]+?)(?<=\S)\*)
    | (?P<emu>(?<![\w])_(?=\S)(?P<emubody>[^_\n]+?)(?<=\S)_(?![\w]))
    | (?P<strike>~~(?=\S)(?P<strikebody>[\s\S]+?)(?<=\S)~~)
    | (?P<mark>==(?=\S)(?P<markbody>[\s\S]+?)(?<=\S)==)
    | (?P<rawhtml></?(?P<rawtag>[A-Za-z][\w:-]*)(?:\s[^<>]*)?/?>)
    | (?P<bareurl>(?<![\w"'=/])(?:https?://|www\.)[^\s<>()\[\]"']+[^\s<>()\[\]"'.,;:!?])
    | (?P<hardbreak>(?:  |\\)\n)
    """,
    re.VERBOSE,
)

# Inline tags that survive the escaping pass, so an author can reach for real
# HTML when Markdown has no spelling for what they mean.
_INLINE_HTML_ALLOWED = {
    "kbd", "br", "sub", "sup", "abbr", "mark", "small", "u", "s", "del", "ins",
    "span", "code", "samp", "var", "cite", "q", "time", "bdi", "wbr", "b", "i", "em", "strong",
}


class _InlineRenderer:
    def __init__(self, parser: "Markdown") -> None:
        self.parser = parser

    def render(self, text: str) -> str:
        out: list[str] = []
        position = 0
        for match in _INLINE_PATTERN.finditer(text):
            start, end = match.span()
            if start > position:
                out.append(self._text(text[position:start]))
            out.append(self._dispatch(match))
            position = end
        if position < len(text):
            out.append(self._text(text[position:]))
        return "".join(out)

    # -- leaf text -------------------------------------------------------- #

    @staticmethod
    def _text(raw: str) -> str:
        escaped = html.escape(raw, quote=False)
        # Typographic niceties that never appear inside code.
        escaped = escaped.replace("...", "&#8230;")
        escaped = re.sub(r"(?<=\w)--(?=\w)", "&#8211;", escaped)
        return escaped

    # -- dispatch --------------------------------------------------------- #

    def _dispatch(self, match: re.Match[str]) -> str:
        group = match.lastgroup or ""
        groups = match.groupdict()

        if groups.get("escape"):
            return html.escape(groups["escape"][1], quote=False)

        if groups.get("code") is not None and match.group("codebody") is not None:
            body = match.group("codebody")
            if body.startswith(" ") and body.endswith(" ") and body.strip():
                body = body[1:-1]
            return f"<code>{html.escape(body, quote=False)}</code>"

        if groups.get("autolink"):
            url = match.group("autourl")
            self.parser._record_link(url)
            label = url[7:] if url.startswith("mailto:") else url
            return f'<a href="{_attr(url)}"{self.parser._link_extra(url)}>{html.escape(label, quote=False)}</a>'

        if groups.get("image"):
            return self.parser._render_image(
                alt=match.group("alt") or "",
                src=(match.group("isrc") or "").strip("<>"),
                title=_strip_quotes(match.group("ititle")),
            )

        if groups.get("refimage"):
            reference = self.parser.references.get((match.group("rimgid") or match.group("ralt")).lower())
            if reference:
                return self.parser._render_image(alt=match.group("ralt") or "", src=reference[0], title=reference[1])
            return self._text(match.group(0))

        if groups.get("link"):
            href = self.parser._safe_href((match.group("lhref") or "").strip("<>"))
            inner = self.render(match.group("ltext") or "")
            if href is None:
                return inner  # refused scheme: keep the words, drop the link
            self.parser._record_link(href)
            title = _strip_quotes(match.group("ltitle"))
            title_attr = f' title="{_attr(title)}"' if title else ""
            return f'<a href="{_attr(href)}"{title_attr}{self.parser._link_extra(href)}>{inner}</a>'

        if groups.get("reflink"):
            key = (match.group("refid") or match.group("rtext") or "").lower()
            reference = self.parser.references.get(key)
            if reference:
                href = self.parser._safe_href(reference[0])
                inner = self.render(match.group("rtext") or "")
                if href is None:
                    return inner
                self.parser._record_link(href)
                title_attr = f' title="{_attr(reference[1])}"' if reference[1] else ""
                return f'<a href="{_attr(href)}"{title_attr}{self.parser._link_extra(href)}>{inner}</a>'
            return self._text(match.group(0))

        if groups.get("footnote"):
            return self.parser._render_footnote_reference(match.group("fnid"))

        if groups.get("kbd"):
            keys = [key.strip() for key in re.split(r"\s*\+\s*", match.group("kbdbody")) if key.strip()]
            rendered = "<span class=\"kbd-sep\">+</span>".join(
                f"<kbd>{html.escape(key, quote=False)}</kbd>" for key in keys
            )
            return f'<span class="kbd-combo">{rendered}</span>'

        if groups.get("strongem"):
            return f"<strong><em>{self.render(match.group('sebody'))}</em></strong>"
        if groups.get("strong"):
            return f"<strong>{self.render(match.group('strongbody'))}</strong>"
        if groups.get("strongu"):
            return f"<strong>{self.render(match.group('strongubody'))}</strong>"
        if groups.get("em"):
            return f"<em>{self.render(match.group('embody'))}</em>"
        if groups.get("emu"):
            return f"<em>{self.render(match.group('emubody'))}</em>"
        if groups.get("strike"):
            return f"<del>{self.render(match.group('strikebody'))}</del>"
        if groups.get("mark"):
            return f"<mark>{self.render(match.group('markbody'))}</mark>"

        if groups.get("rawhtml"):
            tag = (match.group("rawtag") or "").lower()
            if tag in _INLINE_HTML_ALLOWED:
                return sanitize_html(match.group(0))
            return self._text(match.group(0))

        if groups.get("bareurl"):
            url = match.group("bareurl")
            href = url if url.startswith("http") else f"https://{url}"
            self.parser._record_link(href)
            return f'<a href="{_attr(href)}"{self.parser._link_extra(href)}>{html.escape(url, quote=False)}</a>'

        if groups.get("hardbreak"):
            return "<br />\n"

        return self._text(match.group(0))


def _strip_quotes(value: str | None) -> str:
    if not value:
        return ""
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


# --------------------------------------------------------------------------- #
# Block-level patterns
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\n]*)$")
_HEADING_RE = re.compile(r"^[ \t]{0,3}(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t]*#*[ \t]*$")
_SETEXT_RE = re.compile(r"^[ \t]{0,3}(?P<rule>=+|-+)[ \t]*$")
_HR_RE = re.compile(r"^[ \t]{0,3}(?:\*[ \t]*){3,}$|^[ \t]{0,3}(?:-[ \t]*){3,}$|^[ \t]{0,3}(?:_[ \t]*){3,}$")
_QUOTE_RE = re.compile(r"^[ \t]{0,3}>[ \t]?(?P<text>.*)$")
_LIST_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<bullet>[-*+]|\d{1,9}[.)])[ \t]+(?P<text>.*)$")
_EMPTY_LIST_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<bullet>[-*+]|\d{1,9}[.)])[ \t]*$")
_TASK_RE = re.compile(r"^\[(?P<state>[ xX])\][ \t]+(?P<text>.*)$")
_CONTAINER_RE = re.compile(r"^[ \t]{0,3}(?P<colons>:{3,})[ \t]*(?P<name>[A-Za-z][\w-]*)?[ \t]*(?P<attrs>.*)$")
_FOOTNOTE_DEF_RE = re.compile(r"^[ \t]{0,3}\[\^(?P<id>[^\]\s]+)\]:[ \t]*(?P<text>.*)$")
_REFERENCE_DEF_RE = re.compile(r"^[ \t]{0,3}\[(?P<id>[^\]^][^\]]*)\]:[ \t]*(?P<url><[^>]*>|\S+)(?:[ \t]+(?P<title>\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$")
_TABLE_DIVIDER_RE = re.compile(r"^[ \t]{0,3}\|?[ \t]*:?-{1,}:?[ \t]*(?:\|[ \t]*:?-{1,}:?[ \t]*)*\|?[ \t]*$")
_HTML_BLOCK_RE = re.compile(r"^[ \t]{0,3}<(?P<tag>[A-Za-z][\w:-]*)")

_CALLOUT_ICONS = {
    "note": "i",
    "tip": "*",
    "warning": "!",
    "danger": "x",
    "success": "+",
    "info": "i",
    "quote": '"',
}

_CALLOUT_TITLES = {
    "es": {
        "note": "Nota",
        "tip": "Truco",
        "warning": "Aviso",
        "danger": "Peligro",
        "success": "Confirmado",
        "info": "Info",
        "quote": "Cita",
    },
    "en": {
        "note": "Note",
        "tip": "Tip",
        "warning": "Warning",
        "danger": "Danger",
        "success": "Confirmed",
        "info": "Info",
        "quote": "Quote",
    },
}


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

class Markdown:
    """Converts Markdown source into HTML plus structural metadata."""

    def __init__(self, *, lang: str = "es", base_url: str = "", heading_offset: int = 0) -> None:
        self.lang = lang if lang in _CALLOUT_TITLES else "es"
        self.base_url = base_url.rstrip("/")
        self.heading_offset = heading_offset
        self.inline = _InlineRenderer(self)
        self.reset()

    # -- state ------------------------------------------------------------ #

    def reset(self) -> None:
        self.references: dict[str, tuple[str, str]] = {}
        self.footnote_definitions: dict[str, str] = {}
        self.footnote_order: list[str] = []
        self.footnote_backrefs: dict[str, int] = {}
        self.headings: list[Heading] = []
        self.slug_counts: dict[str, int] = {}
        self.links: list[str] = []
        self.media: list[str] = []
        self.code_languages: list[str] = []

    # -- public ----------------------------------------------------------- #

    def convert(self, source: str) -> MarkdownResult:
        self.reset()
        text = source.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
        lines = text.split("\n")
        lines = self._collect_definitions(lines)
        body = self._parse_blocks(lines)
        body += self._render_footnote_section()
        result = MarkdownResult(
            html=body,
            headings=list(self.headings),
            links=list(dict.fromkeys(self.links)),
            media=list(dict.fromkeys(self.media)),
            code_languages=sorted(set(self.code_languages)),
            word_count=len(plain_text(body).split()),
        )
        result.excerpt = self._build_excerpt(body)
        return result

    # -- definition harvesting -------------------------------------------- #

    def _collect_definitions(self, lines: list[str]) -> list[str]:
        """Pull link references and footnote definitions out of the stream."""
        remaining: list[str] = []
        index = 0
        total = len(lines)
        in_fence: str | None = None

        while index < total:
            line = lines[index]

            fence_match = _FENCE_RE.match(line)
            if fence_match:
                marker = fence_match.group("fence")[0]
                if in_fence is None:
                    in_fence = marker
                elif in_fence == marker and not fence_match.group("info"):
                    in_fence = None
                remaining.append(line)
                index += 1
                continue
            if in_fence is not None:
                remaining.append(line)
                index += 1
                continue

            footnote = _FOOTNOTE_DEF_RE.match(line)
            if footnote:
                identifier = footnote.group("id")
                collected = [footnote.group("text")]
                index += 1
                while index < total:
                    nxt = lines[index]
                    if not nxt.strip():
                        # A blank line only ends the note if the next line is
                        # not an indented continuation.
                        if index + 1 < total and lines[index + 1].startswith(("    ", "\t")):
                            collected.append("")
                            index += 1
                            continue
                        break
                    if nxt.startswith(("    ", "\t")):
                        collected.append(nxt[4:] if nxt.startswith("    ") else nxt[1:])
                        index += 1
                        continue
                    if _FOOTNOTE_DEF_RE.match(nxt) or _REFERENCE_DEF_RE.match(nxt):
                        break
                    collected.append(nxt)
                    index += 1
                self.footnote_definitions[identifier] = "\n".join(collected).strip()
                continue

            reference = _REFERENCE_DEF_RE.match(line)
            if reference:
                url = reference.group("url").strip("<>")
                title = _strip_quotes(reference.group("title") or "").strip("()")
                self.references[reference.group("id").lower()] = (url, title)
                index += 1
                continue

            remaining.append(line)
            index += 1

        return remaining

    # -- block parsing ---------------------------------------------------- #

    def _parse_blocks(self, lines: Sequence[str]) -> str:
        out: list[str] = []
        index = 0
        total = len(lines)

        while index < total:
            line = lines[index]

            if not line.strip():
                index += 1
                continue

            fence = _FENCE_RE.match(line)
            if fence and fence.group("fence"):
                chunk, index = self._read_fence(lines, index, fence)
                out.append(chunk)
                continue

            container = _CONTAINER_RE.match(line)
            if container and container.group("name"):
                chunk, index = self._read_container(lines, index, container)
                out.append(chunk)
                continue

            heading = _HEADING_RE.match(line)
            if heading:
                out.append(self._render_heading(len(heading.group("hashes")), heading.group("text")))
                index += 1
                continue

            if _HR_RE.match(line):
                out.append('<hr class="rule" />')
                index += 1
                continue

            if _QUOTE_RE.match(line):
                chunk, index = self._read_blockquote(lines, index)
                out.append(chunk)
                continue

            if _LIST_RE.match(line) or _EMPTY_LIST_RE.match(line):
                chunk, index = self._read_list(lines, index)
                out.append(chunk)
                continue

            if "|" in line and index + 1 < total and _TABLE_DIVIDER_RE.match(lines[index + 1]) and "|" in lines[index + 1]:
                chunk, index = self._read_table(lines, index)
                out.append(chunk)
                continue

            html_block = _HTML_BLOCK_RE.match(line)
            if html_block:
                chunk, index = self._read_html_block(lines, index)
                out.append(chunk)
                continue

            chunk, index = self._read_paragraph(lines, index)
            if chunk:
                out.append(chunk)

        return "\n".join(part for part in out if part)

    # -- fences ----------------------------------------------------------- #

    def _read_fence(self, lines: Sequence[str], index: int, match: re.Match[str]) -> tuple[str, int]:
        marker = match.group("fence")
        info = (match.group("info") or "").strip()
        indent = len(match.group("indent") or "")
        body: list[str] = []
        index += 1
        total = len(lines)
        closing = re.compile(r"^[ \t]*" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}[ \t]*$")
        while index < total and not closing.match(lines[index]):
            raw = lines[index]
            body.append(raw[indent:] if indent and raw[:indent].strip() == "" else raw)
            index += 1
        index += 1  # consume the closing fence (or fall off the end harmlessly)
        return self._render_code_block("\n".join(body), info), index

    def _render_code_block(self, code: str, info: str) -> str:
        parts = info.split(None, 1)
        language_token = parts[0] if parts else ""
        attributes = _parse_attributes(parts[1] if len(parts) > 1 else "")
        # `lang=` in the attribute soup wins over a bare first token.
        language = resolve_language(attributes.get("lang") or language_token)
        self.code_languages.append(language)

        title = attributes.get("title") or attributes.get("file") or ""
        emphasise = _parse_line_ranges(attributes.get("highlight", "") or attributes.get("hl", ""))
        show_numbers = "numbers" in attributes or "linenos" in attributes or bool(emphasise)
        start_number = int(attributes.get("start", "1") or 1) if (attributes.get("start", "1") or "1").isdigit() else 1

        code = code.rstrip("\n")
        rendered = highlight_lines(
            code,
            language,
            emphasise=sorted(emphasise),
            start_number=start_number,
            show_numbers=show_numbers,
        )

        label = title or language
        header = (
            '<div class="code-head">'
            f'<span class="code-lang" aria-hidden="true">{html.escape(label, quote=False)}</span>'
            f'<button type="button" class="code-copy" data-action="copy-code" '
            f'aria-label="{_attr(self._t("Copiar código", "Copy code"))}">'
            f'<span class="code-copy-label">{self._t("copiar", "copy")}</span>'
            "</button>"
            "</div>"
        )
        wrapper_classes = "code-block"
        if attributes.get("class"):
            safe_extra = re.sub(r"[^\w \-]", "", attributes["class"])
            wrapper_classes += " " + safe_extra
        return (
            f'<figure class="{wrapper_classes}" data-lang="{_attr(language)}">'
            f"{header}"
            f'<pre class="code" tabindex="0"><code class="language-{_attr(language)}">{rendered}</code></pre>'
            "</figure>"
        )

    # -- containers ------------------------------------------------------- #

    def _read_container(self, lines: Sequence[str], index: int, match: re.Match[str]) -> tuple[str, int]:
        colons = match.group("colons")
        name = (match.group("name") or "").lower()
        attributes = _parse_attributes(match.group("attrs") or "")
        depth = 1
        body: list[str] = []
        index += 1
        total = len(lines)
        while index < total:
            candidate = _CONTAINER_RE.match(lines[index])
            if candidate and candidate.group("colons") and len(candidate.group("colons")) >= len(colons):
                if candidate.group("name"):
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
            body.append(lines[index])
            index += 1
        return self._render_container(name, attributes, body), index

    def _render_container(self, name: str, attributes: dict[str, str], body: Sequence[str]) -> str:
        if name == "gif":
            return self._render_gif(attributes, body)
        if name == "terminal":
            return self._render_terminal(attributes, body)
        if name == "spoiler":
            summary = attributes.get("title") or self._t("Mostrar solución", "Reveal")
            inner = self._parse_blocks(body)
            return (
                '<details class="spoiler">'
                f'<summary><span class="spoiler-mark" aria-hidden="true">[+]</span> {self.inline.render(summary)}</summary>'
                f'<div class="spoiler-body">{inner}</div>'
                "</details>"
            )
        if name == "timeline":
            return self._render_timeline(attributes, body)
        if name == "figure":
            inner = self._parse_blocks(body)
            caption = attributes.get("caption", "")
            caption_html = f'<figcaption>{self.inline.render(caption)}</figcaption>' if caption else ""
            return f'<figure class="block-figure">{inner}{caption_html}</figure>'
        if name == "references":
            inner = self._parse_blocks(body)
            title = attributes.get("title") or self._t("Referencias", "References")
            return (
                '<section class="references" aria-labelledby="refs-heading">'
                f'<h2 id="refs-heading" class="references-title">{self.inline.render(title)}</h2>'
                f"{inner}</section>"
            )
        if name == "columns":
            inner = self._parse_blocks(body)
            count = attributes.get("count", "2")
            count = count if count in ("2", "3") else "2"
            return f'<div class="columns columns-{count}">{inner}</div>'

        # Default: a callout.
        kind = name if name in _CALLOUT_ICONS else "note"
        title = attributes.get("title") or _CALLOUT_TITLES[self.lang].get(kind, kind.title())
        icon = _CALLOUT_ICONS.get(kind, "i")
        inner = self._parse_blocks(body)
        return (
            f'<aside class="callout callout-{kind}" role="note">'
            f'<p class="callout-title"><span class="callout-icon" aria-hidden="true">[{html.escape(icon, quote=False)}]</span>'
            f"{self.inline.render(title)}</p>"
            f'<div class="callout-body">{inner}</div>'
            "</aside>"
        )

    def _render_terminal(self, attributes: dict[str, str], body: Sequence[str]) -> str:
        title = attributes.get("title") or attributes.get("host") or "czrxplo1t@lab"
        code = "\n".join(body).rstrip("\n")
        rendered = highlight_lines(code, "console", show_numbers=False)
        return (
            '<figure class="terminal-block">'
            '<div class="terminal-chrome" aria-hidden="true">'
            '<span class="dot dot-r"></span><span class="dot dot-y"></span><span class="dot dot-g"></span>'
            f'<span class="terminal-title">{html.escape(title, quote=False)}</span>'
            "</div>"
            f'<pre class="code terminal" tabindex="0"><code>{rendered}</code></pre>'
            "</figure>"
        )

    def _render_timeline(self, attributes: dict[str, str], body: Sequence[str]) -> str:
        items: list[str] = []
        for line in body:
            if not line.strip():
                continue
            stripped = line.lstrip("-* \t")
            date_part, _, rest = stripped.partition(" — ")
            if not rest:
                date_part, _, rest = stripped.partition(" - ")
            if not rest:
                date_part, rest = "", stripped
            items.append(
                '<li class="timeline-item">'
                + (f'<time class="timeline-date">{html.escape(date_part.strip(), quote=False)}</time>' if date_part else "")
                + f'<span class="timeline-text">{self.inline.render(rest.strip())}</span>'
                "</li>"
            )
        title = attributes.get("title", "")
        heading = f'<p class="timeline-title">{self.inline.render(title)}</p>' if title else ""
        return f'<div class="timeline-wrap">{heading}<ol class="timeline">{"".join(items)}</ol></div>'

    def _render_gif(self, attributes: dict[str, str], body: Sequence[str]) -> str:
        """Click-to-play animated media with a static poster.

        The markup degrades cleanly: with JavaScript off the ``<noscript>``
        branch shows the animation directly, and the poster image is a real
        ``<img>`` so the layout never depends on script execution.
        """
        src = attributes.get("src", "")
        poster = attributes.get("poster", "")
        if not is_safe_url(src, allow_data_images=True):
            src = ""
        if not is_safe_url(poster, allow_data_images=True):
            poster = ""
        if not src and not poster:
            return ""
        alt = attributes.get("alt", "")
        caption = attributes.get("caption", "") or " ".join(line.strip() for line in body if line.strip())
        width = attributes.get("width", "")
        height = attributes.get("height", "")
        autoplay = "autoplay" in attributes

        if src:
            self.media.append(src)
        if poster:
            self.media.append(poster)

        dimensions = ""
        if width.isdigit() and height.isdigit():
            dimensions = f' width="{_attr(width)}" height="{_attr(height)}"'

        is_video = src.lower().endswith((".mp4", ".webm", ".mov"))
        classes = "gif-figure" + (" is-autoplay" if autoplay else "")

        if is_video:
            media = (
                f'<video class="gif-media" preload="none" loop muted playsinline'
                f'{" poster=" + chr(34) + _attr(poster) + chr(34) if poster else ""}{dimensions}'
                f' aria-label="{_attr(alt or caption)}">'
                f'<source src="{_attr(src)}" type="video/{"webm" if src.endswith(".webm") else "mp4"}" />'
                "</video>"
            )
            noscript = (
                f'<noscript><video class="gif-media" controls loop muted playsinline{dimensions}>'
                f'<source src="{_attr(src)}" /></video></noscript>'
            )
        else:
            display = poster or src
            media = (
                f'<img class="gif-media" src="{_attr(display)}" data-gif="{_attr(src)}"'
                f' alt="{_attr(alt)}"{dimensions} loading="lazy" decoding="async" />'
            )
            noscript = f'<noscript><img src="{_attr(src)}" alt="{_attr(alt)}"{dimensions} /></noscript>'

        button = (
            '<button type="button" class="gif-toggle" data-action="toggle-gif"'
            f' aria-label="{_attr(self._t("Reproducir animación", "Play animation"))}">'
            '<span class="gif-toggle-icon" aria-hidden="true">▶</span>'
            f'<span class="gif-toggle-text">GIF</span></button>'
        )
        caption_html = f'<figcaption class="gif-caption">{self.inline.render(caption)}</figcaption>' if caption else ""
        return (
            f'<figure class="{classes}">'
            f'<div class="gif-frame">{media}{button}{noscript}</div>'
            f"{caption_html}</figure>"
        )

    # -- quotes, lists, tables -------------------------------------------- #

    def _read_blockquote(self, lines: Sequence[str], index: int) -> tuple[str, int]:
        collected: list[str] = []
        total = len(lines)
        while index < total:
            match = _QUOTE_RE.match(lines[index])
            if match:
                collected.append(match.group("text"))
                index += 1
                continue
            # Lazy continuation: a plain line right after a quote line stays in.
            if lines[index].strip() and collected and not _LIST_RE.match(lines[index]) and not _HEADING_RE.match(lines[index]):
                collected.append(lines[index])
                index += 1
                continue
            break

        # GitHub-style alert syntax: > [!WARNING]
        alert = re.match(r"^\[!(?P<kind>[A-Za-z]+)\]\s*$", collected[0].strip()) if collected else None
        if alert:
            kind = alert.group("kind").lower()
            mapping = {"note": "note", "tip": "tip", "important": "info", "warning": "warning", "caution": "danger"}
            return self._render_container(mapping.get(kind, "note"), {}, collected[1:]), index

        inner = self._parse_blocks(collected)
        return f"<blockquote>{inner}</blockquote>", index

    def _read_list(self, lines: Sequence[str], index: int) -> tuple[str, int]:
        total = len(lines)
        first = _LIST_RE.match(lines[index]) or _EMPTY_LIST_RE.match(lines[index])
        assert first is not None
        base_indent = len(first.group("indent"))
        bullet = first.group("bullet")
        ordered = bullet[0].isdigit()
        start = int(re.sub(r"\D", "", bullet) or 1) if ordered else 1

        items: list[list[str]] = []
        current: list[str] | None = None
        loose = False
        pending_blank = False

        while index < total:
            line = lines[index]

            if not line.strip():
                pending_blank = True
                index += 1
                continue

            match = _LIST_RE.match(line) or _EMPTY_LIST_RE.match(line)
            indent = len(line) - len(line.lstrip())

            if match and len(match.group("indent")) == base_indent:
                item_is_ordered = match.group("bullet")[0].isdigit()
                if item_is_ordered != ordered:
                    break
                if pending_blank and current is not None:
                    loose = True
                current = [match.groupdict().get("text", "") or ""]
                items.append(current)
                pending_blank = False
                index += 1
                continue

            if current is not None and indent > base_indent:
                if pending_blank:
                    current.append("")
                    loose = True
                    pending_blank = False
                current.append(line[base_indent + 2:] if len(line) > base_indent + 2 else line.strip())
                index += 1
                continue

            if current is not None and not pending_blank and not match:
                # Lazy paragraph continuation inside the current item.
                current.append(line.strip())
                index += 1
                continue

            break

        rendered_items: list[str] = []
        for item in items:
            rendered_items.append(self._render_list_item(item, loose))

        tag = "ol" if ordered else "ul"
        start_attr = f' start="{start}"' if ordered and start != 1 else ""
        has_tasks = any('class="task-item' in item for item in rendered_items)
        classes = "md-list" + (" task-list" if has_tasks else "") + (" is-loose" if loose else "")
        return f'<{tag} class="{classes}"{start_attr}>{"".join(rendered_items)}</{tag}>', index

    def _render_list_item(self, item_lines: list[str], loose: bool) -> str:
        text = list(item_lines)
        task = _TASK_RE.match(text[0]) if text else None
        classes = "md-item"
        prefix = ""
        if task:
            done = task.group("state").lower() == "x"
            text[0] = task.group("text")
            classes = f"task-item{' is-done' if done else ''}"
            prefix = (
                f'<span class="task-box" aria-hidden="true">[{"x" if done else " "}]</span>'
                f'<span class="sr-only">{self._t("hecho" if done else "pendiente", "done" if done else "todo")}: </span>'
            )

        multiline = len([line for line in text if line.strip()]) > 1 or any(
            _LIST_RE.match(line) or _FENCE_RE.match(line) or _CONTAINER_RE.match(line) and _CONTAINER_RE.match(line).group("name")  # type: ignore[union-attr]
            for line in text[1:]
        )

        if multiline or loose:
            inner = self._parse_blocks(text)
            if not loose:
                # Tight list: unwrap the leading paragraph so the bullet text
                # sits inline, but keep any nested block that follows it.
                unwrapped = re.match(r"^<p>([\s\S]*?)</p>\n?([\s\S]*)$", inner)
                if unwrapped and "<p>" not in unwrapped.group(1):
                    inner = unwrapped.group(1) + unwrapped.group(2)
            return f'<li class="{classes}">{prefix}{inner}</li>'
        return f'<li class="{classes}">{prefix}{self.inline.render(" ".join(text).strip())}</li>'

    def _read_table(self, lines: Sequence[str], index: int) -> tuple[str, int]:
        header_cells = _split_row(lines[index])
        alignments = _parse_alignments(lines[index + 1])
        index += 2
        rows: list[list[str]] = []
        total = len(lines)
        while index < total and lines[index].strip() and "|" in lines[index]:
            rows.append(_split_row(lines[index]))
            index += 1

        def cell(content: str, position: int, tag: str) -> str:
            align = alignments[position] if position < len(alignments) else ""
            class_attr = f' class="ta-{align}"' if align else ""
            scope = ' scope="col"' if tag == "th" else ""
            return f"<{tag}{class_attr}{scope}>{self.inline.render(content)}</{tag}>"

        head = "".join(cell(value, position, "th") for position, value in enumerate(header_cells))
        body_rows: list[str] = []
        for row in rows:
            padded = row + [""] * (len(header_cells) - len(row))
            body_rows.append("<tr>" + "".join(cell(value, position, "td") for position, value in enumerate(padded[:len(header_cells)])) + "</tr>")

        return (
            '<div class="table-wrap" tabindex="0" role="region">'
            f'<table class="md-table"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table></div>',
            index,
        )

    def _read_html_block(self, lines: Sequence[str], index: int) -> tuple[str, int]:
        collected: list[str] = []
        total = len(lines)
        while index < total and lines[index].strip():
            collected.append(lines[index])
            index += 1
        fragment = "\n".join(collected)
        for match in re.finditer(r'(?:src|href|poster)\s*=\s*"([^"]+)"', fragment):
            self._record_link(match.group(1))
        return sanitize_html(fragment), index

    def _read_paragraph(self, lines: Sequence[str], index: int) -> tuple[str, int]:
        collected: list[str] = []
        total = len(lines)
        while index < total:
            line = lines[index]
            if not line.strip():
                break
            if _HEADING_RE.match(line) or _HR_RE.match(line) or _QUOTE_RE.match(line):
                break
            fence = _FENCE_RE.match(line)
            if fence and fence.group("fence"):
                break
            container = _CONTAINER_RE.match(line)
            if container and container.group("name"):
                break
            if collected and (_LIST_RE.match(line) or _EMPTY_LIST_RE.match(line)):
                break
            if _SETEXT_RE.match(line) and collected:
                level = 1 if line.strip().startswith("=") else 2
                text = " ".join(collected).strip()
                index += 1
                return self._render_heading(level, text), index
            collected.append(line)
            index += 1

        if not collected:
            return "", index

        text = "\n".join(collected).strip()
        if not text:
            return "", index

        rendered = self.inline.render(text)

        # A paragraph that is nothing but one image becomes a figure.
        only_image = re.fullmatch(r'\s*(<figure class="gif-figure">[\s\S]*</figure>|<img [^>]*/>)\s*', rendered)
        if only_image:
            content = only_image.group(1)
            if content.startswith("<figure"):
                return content, index
            return f'<figure class="img-figure">{content}</figure>', index

        return f"<p>{rendered}</p>", index

    # -- headings, links, media ------------------------------------------- #

    def _render_heading(self, level: int, text: str) -> str:
        level = max(1, min(6, level + self.heading_offset))
        inline_html = self.inline.render(text.strip())
        label = plain_text(inline_html)
        base = slugify(label)
        count = self.slug_counts.get(base, 0)
        self.slug_counts[base] = count + 1
        slug = base if count == 0 else f"{base}-{count + 1}"
        self.headings.append(Heading(level=level, text=label, slug=slug))
        anchor = (
            f'<a class="heading-anchor" href="#{_attr(slug)}" '
            f'aria-label="{_attr(self._t("Enlace a esta sección", "Link to this section"))}">#</a>'
        )
        return f'<h{level} id="{_attr(slug)}" class="heading heading-{level}">{inline_html}{anchor}</h{level}>'

    def _safe_href(self, href: str) -> str | None:
        """Vet a URL before it reaches an attribute.

        Returns the URL when it is fit to emit, or ``None`` when the scheme is
        refused.  Callers drop the link and keep the text rather than emitting
        a dead ``href``, so a bad URL is visible in review instead of silently
        producing a broken anchor.
        """
        candidate = (href or "").strip()
        if not candidate or candidate.startswith("#"):
            return candidate
        return candidate if is_safe_url(candidate) else None

    def _record_link(self, href: str) -> None:
        if href and not href.startswith("#"):
            self.links.append(href)

    def _link_extra(self, href: str) -> str:
        """External links get the safety attributes; internal ones stay clean."""
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", href) and not href.lower().startswith("mailto:"):
            return ' target="_blank" rel="noopener noreferrer" class="ext"'
        return ""

    def _render_image(self, *, alt: str, src: str, title: str) -> str:
        if not is_safe_url(src, allow_data_images=True):
            # Refused source: fall back to the alt text so the meaning survives.
            return html.escape(alt or "", quote=False)
        if src:
            self.media.append(src)
        title_attr = f' title="{_attr(title)}"' if title else ""
        classes = "content-img"
        if src.lower().endswith(".gif"):
            classes += " is-gif"
        return (
            f'<img class="{classes}" src="{_attr(src)}" alt="{_attr(alt)}"{title_attr} '
            'loading="lazy" decoding="async" />'
        )

    # -- footnotes -------------------------------------------------------- #

    def _render_footnote_reference(self, identifier: str) -> str:
        if identifier not in self.footnote_definitions:
            return html.escape(f"[^{identifier}]", quote=False)
        if identifier not in self.footnote_order:
            self.footnote_order.append(identifier)
        number = self.footnote_order.index(identifier) + 1
        occurrence = self.footnote_backrefs.get(identifier, 0) + 1
        self.footnote_backrefs[identifier] = occurrence
        ref_id = f"fnref-{slugify(identifier)}" + ("" if occurrence == 1 else f"-{occurrence}")
        return (
            f'<sup class="footnote-ref"><a id="{_attr(ref_id)}" href="#fn-{_attr(slugify(identifier))}" '
            f'role="doc-noteref" aria-label="{_attr(self._t("Nota", "Footnote"))} {number}">[{number}]</a></sup>'
        )

    def _render_footnote_section(self) -> str:
        if not self.footnote_order:
            return ""
        items: list[str] = []
        for identifier in self.footnote_order:
            slug = slugify(identifier)
            definition = self.footnote_definitions.get(identifier, "")
            inner = self._parse_blocks(definition.split("\n"))
            occurrences = self.footnote_backrefs.get(identifier, 1)
            backrefs = []
            for occurrence in range(1, occurrences + 1):
                ref_id = f"fnref-{slug}" + ("" if occurrence == 1 else f"-{occurrence}")
                suffix = "" if occurrences == 1 else f"<sup>{occurrence}</sup>"
                backrefs.append(
                    f'<a class="footnote-back" href="#{_attr(ref_id)}" role="doc-backlink" '
                    f'aria-label="{_attr(self._t("Volver al texto", "Back to content"))}">↩{suffix}</a>'
                )
            items.append(f'<li id="fn-{_attr(slug)}" class="footnote-item">{inner}<span class="footnote-backs">{"".join(backrefs)}</span></li>')
        title = self._t("Notas", "Notes")
        return (
            '<section class="footnotes" role="doc-endnotes" aria-labelledby="footnotes-heading">'
            f'<h2 id="footnotes-heading" class="footnotes-title">{title}</h2>'
            f'<ol class="footnote-list">{"".join(items)}</ol></section>'
        )

    # -- misc ------------------------------------------------------------- #

    def _build_excerpt(self, body: str, *, length: int = 240) -> str:
        for match in re.finditer(r"<p>([\s\S]*?)</p>", body):
            text = plain_text(match.group(1))
            if len(text) < 40:
                continue
            if len(text) <= length:
                return text
            return text[:length].rsplit(" ", 1)[0] + "…"
        text = plain_text(body)
        return text[:length].rsplit(" ", 1)[0] + "…" if len(text) > length else text

    def _t(self, spanish: str, english: str) -> str:
        return spanish if self.lang == "es" else english


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _parse_alignments(line: str) -> list[str]:
    alignments: list[str] = []
    for cell in _split_row(line):
        cell = cell.strip()
        if cell.startswith(":") and cell.endswith(":"):
            alignments.append("center")
        elif cell.endswith(":"):
            alignments.append("right")
        elif cell.startswith(":"):
            alignments.append("left")
        else:
            alignments.append("")
    return alignments


def render_markdown(source: str, *, lang: str = "es", base_url: str = "") -> MarkdownResult:
    """One-shot convenience wrapper."""
    return Markdown(lang=lang, base_url=base_url).convert(source)
