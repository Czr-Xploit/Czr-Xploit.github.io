"""
Syndication and machine-readable outputs: RSS 2.0, Atom, JSON Feed,
sitemap.xml and robots.txt.

Two rules govern everything here:

1. Every URL emitted is absolute.  Feed readers and crawlers do not share the
   page's base, and a relative URL in a feed is a silent 404 for the reader.
2. Every piece of text goes through XML escaping, not HTML escaping.  They
   differ: XML has no named entities beyond the five built-ins, so ``&nbsp;``
   in a title is a parse error in a feed that would have been harmless in a
   page.  ``_xml_text`` normalises that away.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from typing import Any, Iterable, Sequence

from .content import Document
from .markdown import plain_text

__all__ = [
    "render_rss",
    "render_atom",
    "render_json_feed",
    "render_sitemap",
    "render_robots",
    "render_security_txt",
]


# Characters XML 1.0 forbids outright, regardless of escaping.
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _xml_text(value: Any) -> str:
    """Escape for XML text or attribute content."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _ILLEGAL_XML.sub("", text)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _cdata(value: str) -> str:
    """Wrap HTML in CDATA, splitting any literal ``]]>`` that would close it."""
    safe = _ILLEGAL_XML.sub("", value or "").replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def _rfc2822(value: dt.date | dt.datetime) -> str:
    moment = value if isinstance(value, dt.datetime) else dt.datetime.combine(value, dt.time(12, 0))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return (
        f"{days[moment.weekday()]}, {moment.day:02d} {months[moment.month - 1]} {moment.year} "
        f"{moment.strftime('%H:%M:%S')} +0000"
    )


def _rfc3339(value: dt.date | dt.datetime) -> str:
    moment = value if isinstance(value, dt.datetime) else dt.datetime.combine(value, dt.time(12, 0))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _absolutise(markup: str, base_url: str) -> str:
    """Rewrite root-relative URLs so the markup survives outside the site."""
    base = base_url.rstrip("/")

    def replace(match: re.Match[str]) -> str:
        attribute, quote, url = match.group(1), match.group(2), match.group(3)
        if url.startswith(("http://", "https://", "mailto:", "data:", "#")):
            return match.group(0)
        if url.startswith("/"):
            return f"{attribute}={quote}{base}{url}{quote}"
        return match.group(0)

    return re.sub(r'\b(href|src|poster)=(["\'])([^"\']*)\2', replace, markup)


# --------------------------------------------------------------------------- #
# RSS 2.0
# --------------------------------------------------------------------------- #

def render_rss(config, documents: Sequence[Document], *, lang: str, feed_url: str, title: str, description: str) -> str:
    language = config.language(lang)
    home = config.absolute(language.url_for())
    built = config.build_timestamp or _rfc2822(dt.datetime.now(dt.timezone.utc))

    items: list[str] = []
    for document in documents:
        link = config.absolute(document.url)
        body = _absolutise(document.rendered.html, config.base_url)
        categories = "".join(f"<category>{_xml_text(tag)}</category>" for tag in document.tags[:8])
        enclosure = ""
        if document.cover:
            cover_url = config.absolute(document.cover)
            mime = "image/gif" if cover_url.endswith(".gif") else "image/webp" if cover_url.endswith(".webp") else "image/png"
            enclosure = f'<enclosure url="{_xml_text(cover_url)}" type="{mime}" length="0" />'
        items.append(
            "<item>"
            f"<title>{_xml_text(document.title)}</title>"
            f"<link>{_xml_text(link)}</link>"
            f'<guid isPermaLink="true">{_xml_text(link)}</guid>'
            f"<pubDate>{_rfc2822(document.date)}</pubDate>"
            f"<description>{_cdata(document.summary)}</description>"
            f"<content:encoded>{_cdata(body)}</content:encoded>"
            f"<dc:creator>{_xml_text(config.author)}</dc:creator>"
            f"{categories}{enclosure}"
            "</item>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>"
        f"<title>{_xml_text(title)}</title>"
        f"<link>{_xml_text(home)}</link>"
        f"<description>{_xml_text(description)}</description>"
        f"<language>{_xml_text(language.locale)}</language>"
        f"<lastBuildDate>{built}</lastBuildDate>"
        f"<generator>czrxplo1t-ssg</generator>"
        f'<atom:link href="{_xml_text(config.absolute(feed_url))}" rel="self" type="application/rss+xml" />'
        f"{''.join(items)}"
        "</channel>\n</rss>\n"
    )


# --------------------------------------------------------------------------- #
# Atom 1.0
# --------------------------------------------------------------------------- #

def render_atom(config, documents: Sequence[Document], *, lang: str, feed_url: str, title: str, description: str) -> str:
    language = config.language(lang)
    home = config.absolute(language.url_for())
    self_url = config.absolute(feed_url)
    latest = max((doc.updated or doc.date for doc in documents), default=dt.date.today())

    entries: list[str] = []
    for document in documents:
        link = config.absolute(document.url)
        body = _absolutise(document.rendered.html, config.base_url)
        categories = "".join(f'<category term="{_xml_text(tag)}" />' for tag in document.tags[:8])
        entries.append(
            "<entry>"
            f"<title>{_xml_text(document.title)}</title>"
            f'<link rel="alternate" type="text/html" href="{_xml_text(link)}" />'
            f"<id>{_xml_text(link)}</id>"
            f"<published>{_rfc3339(document.date)}</published>"
            f"<updated>{_rfc3339(document.updated or document.date)}</updated>"
            f'<summary type="text">{_xml_text(document.summary)}</summary>'
            f'<content type="html">{_cdata(body)}</content>'
            f"{categories}"
            "</entry>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="{_xml_text(lang)}">'
        f"<title>{_xml_text(title)}</title>"
        f"<subtitle>{_xml_text(description)}</subtitle>"
        f'<link rel="alternate" type="text/html" href="{_xml_text(home)}" />'
        f'<link rel="self" type="application/atom+xml" href="{_xml_text(self_url)}" />'
        f"<id>{_xml_text(self_url)}</id>"
        f"<updated>{_rfc3339(latest)}</updated>"
        f"<author><name>{_xml_text(config.author)}</name>"
        + (f"<uri>{_xml_text(config.base_url)}</uri>" if config.base_url else "")
        + "</author>"
        f"<generator>czrxplo1t-ssg</generator>"
        f"{''.join(entries)}"
        "</feed>\n"
    )


# --------------------------------------------------------------------------- #
# JSON Feed 1.1
# --------------------------------------------------------------------------- #

def render_json_feed(config, documents: Sequence[Document], *, lang: str, feed_url: str, title: str, description: str) -> str:
    language = config.language(lang)
    payload: dict[str, Any] = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": title,
        "home_page_url": config.absolute(language.url_for()),
        "feed_url": config.absolute(feed_url),
        "description": description,
        "language": language.locale,
        "authors": [{"name": config.author, "url": config.base_url}],
        "items": [],
    }
    for document in documents:
        item: dict[str, Any] = {
            "id": config.absolute(document.url),
            "url": config.absolute(document.url),
            "title": document.title,
            "summary": document.summary,
            "content_html": _absolutise(document.rendered.html, config.base_url),
            "date_published": _rfc3339(document.date),
            "language": language.locale,
        }
        if document.updated:
            item["date_modified"] = _rfc3339(document.updated)
        if document.tags:
            item["tags"] = document.tags
        if document.cover:
            item["image"] = config.absolute(document.cover)
        payload["items"].append(item)
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n"


# --------------------------------------------------------------------------- #
# sitemap / robots / security.txt
# --------------------------------------------------------------------------- #

def render_sitemap(config, entries: Iterable[dict[str, Any]]) -> str:
    """``entries``: dicts with 'url', optional 'lastmod', 'priority', 'alternates'."""
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for entry in entries:
        location = config.absolute(entry["url"])
        parts.append("<url>")
        parts.append(f"<loc>{_xml_text(location)}</loc>")
        lastmod = entry.get("lastmod")
        if lastmod is not None:
            value = lastmod.isoformat() if hasattr(lastmod, "isoformat") else str(lastmod)
            parts.append(f"<lastmod>{_xml_text(value[:10])}</lastmod>")
        if entry.get("changefreq"):
            parts.append(f"<changefreq>{_xml_text(entry['changefreq'])}</changefreq>")
        if entry.get("priority") is not None:
            parts.append(f"<priority>{float(entry['priority']):.1f}</priority>")
        for code, alternate in (entry.get("alternates") or {}).items():
            parts.append(
                f'<xhtml:link rel="alternate" hreflang="{_xml_text(code)}" '
                f'href="{_xml_text(config.absolute(alternate))}" />'
            )
        parts.append("</url>")
    parts.append("</urlset>")
    return "\n".join(parts) + "\n"


def render_robots(config, *, sitemap_url: str = "/sitemap.xml") -> str:
    return (
        "# CzrXplo1t\n"
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /404.html\n"
        "\n"
        f"Sitemap: {config.absolute(sitemap_url)}\n"
    )


def render_security_txt(config, *, expires: dt.date | None = None) -> str:
    """RFC 9116 security.txt. Expires is mandatory, so it is always emitted."""
    deadline = expires or (dt.date.today().replace(year=dt.date.today().year + 1))
    lines = [
        "# https://www.rfc-editor.org/rfc/rfc9116",
    ]
    if config.email:
        lines.append(f"Contact: mailto:{config.email}")
    lines.append(f"Expires: {deadline.isoformat()}T00:00:00.000Z")
    if config.pgp_key_path:
        lines.append(f"Encryption: {config.absolute(config.pgp_key_path)}")
    lines.append("Preferred-Languages: es, en")
    lines.append(f"Canonical: {config.absolute('/.well-known/security.txt')}")
    return "\n".join(lines) + "\n"
