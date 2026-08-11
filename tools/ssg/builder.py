"""
Build orchestration: turns ``content/`` + ``theme/`` into ``dist/``.

The build is a straight line with no incremental cleverness: wipe the output
directory, load everything, render everything, write everything.  On a site of
this size that takes well under a second, and it removes an entire category of
bug where a stale artefact survives into production because the dependency
graph was wrong.

Determinism is a requirement, not a nicety.  Two builds of the same commit must
produce byte-identical output, so nothing here reads the clock except the
explicitly-passed build timestamp, and every iteration over a set or dict is
sorted before it reaches the output.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import feeds as feeds_module
from .assets import AssetPipeline, human_bytes
from .config import SiteConfig, load_config
from .content import ArsenalEntry, ContentError, Document, Library, load_arsenal, load_documents, normalise_tag
from .i18n import format_date, strings_for
from .search import build_command_index, build_search_index
from .template import Markup, TemplateEngine

__all__ = ["Builder", "BuildResult", "build"]


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #

@dataclass
class BuildResult:
    pages: int = 0
    documents: int = 0
    assets: int = 0
    duration: float = 0.0
    warnings: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    budget_problems: list[str] = field(default_factory=list)
    summary_lines: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.budget_problems


def _output_for(url: str) -> str:
    trimmed = url.strip("/")
    return os.path.join(trimmed, "index.html") if trimmed else "index.html"


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #

class Builder:
    def __init__(
        self,
        config: SiteConfig,
        *,
        include_drafts: bool = False,
        minify: bool = True,
        base_url_override: str | None = None,
        timestamp: dt.datetime | None = None,
    ) -> None:
        self.config = config
        if base_url_override:
            self.config.base_url = base_url_override.rstrip("/")
        self.include_drafts = include_drafts
        self.now = timestamp or dt.datetime.now(dt.timezone.utc)
        self.config.build_timestamp = self.now.strftime("%a, %d %b %Y %H:%M:%S +0000")

        self.assets = AssetPipeline(config, minify=minify)
        self.engine = TemplateEngine(
            [os.path.join(config.theme_path, "templates"), os.path.join(config.theme_path, "partials")]
        )
        self.result = BuildResult()
        self.library: Library | None = None
        self._sitemap: list[dict[str, Any]] = []
        self._register_filters()

    # -- template plumbing ------------------------------------------------ #

    def _register_filters(self) -> None:
        engine = self.engine

        def asset_filter(value: Any) -> str:
            return self.assets.url_for(str(value))

        def absurl_filter(value: Any) -> str:
            return self.config.absolute(str(value))

        def localdate_filter(value: Any, lang: str = "es") -> str:
            return format_date(value, str(lang))

        def isodate_filter(value: Any) -> str:
            return value.isoformat() if hasattr(value, "isoformat") else str(value)

        def tagkey_filter(value: Any) -> str:
            return normalise_tag(str(value))

        engine.filters["asset"] = asset_filter
        engine.filters["absurl"] = absurl_filter
        engine.filters["localdate"] = localdate_filter
        engine.filters["isodate"] = isodate_filter
        engine.filters["tagkey"] = tagkey_filter

    def _base_context(self, lang: str) -> dict[str, Any]:
        language = self.config.language(lang)
        assert self.library is not None
        return {
            "site": self.config,
            "cfg": self.config.as_dict(),
            "lang": lang,
            "language": language,
            "languages": self.config.languages,
            "t": strings_for(lang),
            "nav": self._nav(lang),
            "themes": self.config.themes,
            "default_theme": self.config.default_theme,
            "year": self.now.year,
            "build_date": self.now.strftime("%Y-%m-%d"),
            "csp": self.config.csp_header(),
            "permissions_policy": self.config.permissions_policy,
            "stats": self.library.stats(lang),
            "social": self.config.social,
        }

    def _nav(self, lang: str) -> list[dict[str, str]]:
        language = self.config.language(lang)
        strings = strings_for(lang)
        return [
            {"key": "blog", "label": strings["nav_research"], "url": language.url_for("blog")},
            {"key": "writeups", "label": strings["nav_writeups"], "url": language.url_for("writeups")},
            {"key": "arsenal", "label": strings["nav_arsenal"], "url": language.url_for("arsenal")},
            {"key": "tags", "label": strings["nav_tags"], "url": language.url_for("tags")},
            {"key": "whoami", "label": strings["nav_whoami"], "url": language.url_for("whoami")},
        ]

    def _page(
        self,
        *,
        lang: str,
        title: str,
        description: str,
        url: str,
        section: str = "",
        kind: str = "website",
        image: str = "",
        alternates: dict[str, str] | None = None,
        noindex: bool = False,
        **extra: Any,
    ) -> dict[str, Any]:
        language = self.config.language(lang)
        full_title = title if title == self.config.title else f"{title} :: {self.config.handle}"

        alt = dict(alternates or {})
        alt.setdefault(lang, url)

        # Every language gets a link. When a document has no counterpart in the
        # other language we point at that language's home rather than emitting a
        # dead hreflang, which is worse than no hreflang at all.
        lang_links: list[dict[str, Any]] = []
        for entry in self.config.languages:
            lang_links.append(
                {
                    "code": entry.code,
                    "native": entry.native_name,
                    "url": alt.get(entry.code) or entry.url_for(),
                    "current": entry.code == lang,
                }
            )

        prefix = f"/{language.prefix}" if language.prefix else ""

        return {
            "title": title,
            "full_title": full_title,
            "description": description,
            "url": url,
            "canonical": self.config.absolute(url),
            "section": section,
            "og_type": kind,
            # Every page gets a social card. A shared link with no preview image
            # looks broken, and the generated default costs nothing to serve.
            "image": self.config.absolute(image or "/static/img/og-default.png"),
            "alternates": alt,
            "lang_links": lang_links,
            "default_alternate": alt.get(self.config.default_language, url),
            "noindex": noindex,
            "locale": language.locale,
            # Section URLs the templates link to constantly.
            "home_url": language.url_for(),
            "blog_url": language.url_for("blog"),
            "writeups_url": language.url_for("writeups"),
            "arsenal_url": language.url_for("arsenal"),
            "tags_url": language.url_for("tags"),
            "search_url": language.url_for("search"),
            "feed_url": f"{prefix}/feed.xml",
            "atom_url": f"{prefix}/atom.xml",
            "client_data": self._client_data(lang, section),
            **extra,
        }

    def _client_data(self, lang: str, section: str) -> dict[str, Any]:
        """The JSON blob the front-end reads instead of guessing.

        Kept minimal: URLs the scripts need to fetch, and the handful of
        strings they render. Everything else is already in the DOM.
        """
        language = self.config.language(lang)
        strings = strings_for(lang)
        return {
            "lang": lang,
            "section": section,
            "home": language.url_for(),
            "searchIndex": f"/search-{lang}.json",
            "fsIndex": f"/fs-{lang}.json",
            "themes": self.config.themes,
            "defaultTheme": self.config.default_theme,
            "handle": self.config.handle,
            "languages": [
                {"code": entry.code, "url": entry.url_for(), "native": entry.native_name}
                for entry in self.config.languages
            ],
            "strings": {
                "noResults": strings["no_results"],
                "results": strings["search_results_count"],
                "loading": strings["loading"],
                "copied": strings["link_copied"],
                "copy": strings["copy_link"],
                "readingTime": strings["reading_time"],
                "terminalHint": strings["terminal_hint"],
                "themeSwitch": strings["theme_switch"],
                "menuOpen": strings["menu_open"],
                "menuClose": strings["menu_close"],
            },
        }

    def _render(self, template: str, context: dict[str, Any], url: str) -> None:
        html = self.engine.render(template, context)
        self.assets.write(_output_for(url), html, record=False)
        self.result.pages += 1
        self.result.written.append(url)

    def _track_sitemap(
        self,
        url: str,
        *,
        lastmod: Any = None,
        priority: float = 0.5,
        changefreq: str = "",
        alternates: dict[str, str] | None = None,
    ) -> None:
        entry: dict[str, Any] = {"url": url, "priority": priority}
        if lastmod is not None:
            entry["lastmod"] = lastmod
        if changefreq:
            entry["changefreq"] = changefreq
        if alternates:
            entry["alternates"] = dict(alternates)
            entry["alternates"]["x-default"] = alternates.get(self.config.default_language, url)
        self._sitemap.append(entry)

    # -- main --------------------------------------------------------------#

    def build(self) -> BuildResult:
        started = time.perf_counter()

        self._prepare_output()
        self.assets.copy_static()
        self._bundle_styles()

        documents = load_documents(self.config, include_drafts=self.include_drafts)
        arsenal = load_arsenal(self.config)
        self.library = Library(self.config, documents, arsenal)
        self.result.documents = len(documents)

        for language in self.config.languages:
            code = language.code
            self._build_home(code)
            self._build_listing(code, kind="post", section="blog")
            self._build_listing(code, kind="writeup", section="writeups")
            self._build_arsenal(code)
            self._build_tags(code)
            self._build_search_page(code)
            self._build_documents(code)
            self._build_feeds(code)
            self._build_indexes(code)

        self._build_404()
        self._build_root_files()

        self.result.assets = self.assets.report.copied
        self.result.budget_problems = self.assets.budget_violations()
        self.result.summary_lines = self.assets.summary_lines()
        self.result.duration = time.perf_counter() - started
        return self.result

    # Cascade order matters: tokens define the variables everything else reads,
    # base sets the element defaults, layout places things, components style
    # them, content styles article prose, effects layer the decoration on top.
    CSS_ORDER = (
        "tokens.css",
        "base.css",
        "layout.css",
        "components.css",
        "content.css",
        "effects.css",
    )

    def _bundle_styles(self) -> None:
        source_dir = os.path.join(self.config.theme_path, "css")
        if not os.path.isdir(source_dir):
            return
        missing = [name for name in self.CSS_ORDER if not os.path.isfile(os.path.join(source_dir, name))]
        if missing:
            self.result.warnings.append(f"stylesheets missing from theme/css: {', '.join(missing)}")
        self.assets.bundle_css(
            [name for name in self.CSS_ORDER if name not in missing],
            output="/static/css/main.css",
        )

    def _prepare_output(self) -> None:
        output = self.config.output_path
        if os.path.exists(output):
            if not os.path.isdir(output):
                raise RuntimeError(f"output path exists and is not a directory: {output}")
            # Guard against a misconfigured output_dir wiping the repository.
            marker = os.path.join(output, ".ssg-output")
            if os.listdir(output) and not os.path.exists(marker):
                raise RuntimeError(
                    f"refusing to clean {output!r}: it is not empty and has no .ssg-output marker. "
                    "Delete it by hand if this is really the build directory."
                )
            shutil.rmtree(output)
        os.makedirs(output, exist_ok=True)
        with open(os.path.join(output, ".ssg-output"), "w", encoding="utf-8") as handle:
            handle.write("Generated by tools/ssg. Safe to delete.\n")
        # GitHub Pages runs Jekyll unless told not to; underscore-prefixed
        # paths would silently vanish without this.
        with open(os.path.join(output, ".nojekyll"), "w", encoding="utf-8") as handle:
            handle.write("")

    # -- page builders ---------------------------------------------------- #

    def _alternates_for(self, document: Document) -> dict[str, str]:
        alternates = {document.lang: document.url}
        for code, sibling in document.translations.items():
            alternates[code] = sibling.url
        return alternates

    def _section_alternates(self, *parts: str) -> dict[str, str]:
        return {language.code: language.url_for(*parts) for language in self.config.languages}

    def _build_home(self, lang: str) -> None:
        assert self.library is not None
        language = self.config.language(lang)
        context = self._base_context(lang)
        url = language.url_for()
        featured = self.library.featured(lang, 3)
        latest = self.library.latest(lang, 7)
        context.update(
            {
                "page": self._page(
                    lang=lang,
                    title=self.config.title,
                    description=self.config.description.get(lang, ""),
                    url=url,
                    section="home",
                    alternates=self._section_alternates(),
                ),
                "featured": featured,
                "latest": [doc for doc in latest if doc not in featured][:6],
                "recent_writeups": self.library.writeups(lang)[:4],
                "top_tags": self.library.tag_list(lang)[:18],
                "arsenal_preview": [entry for entry in self.library.arsenal if entry.featured][:6],
            }
        )
        self._render("home.html", context, url)
        self._track_sitemap(url, priority=1.0, changefreq="daily", alternates=self._section_alternates())

    def _build_listing(self, lang: str, *, kind: str, section: str) -> None:
        assert self.library is not None
        language = self.config.language(lang)
        strings = strings_for(lang)
        documents = self.library.by_lang(lang, kind=kind)
        per_page = self.config.posts_per_page
        pages = max(1, (len(documents) + per_page - 1) // per_page)

        title = strings["research_title"] if kind == "post" else strings["writeups_title"]
        intro = strings["research_intro"] if kind == "post" else strings["writeups_intro"]

        for number in range(1, pages + 1):
            chunk = documents[(number - 1) * per_page: number * per_page]
            url = language.url_for(section) if number == 1 else language.url_for(section, "page", str(number))
            context = self._base_context(lang)
            context.update(
                {
                    "page": self._page(
                        lang=lang,
                        title=title if number == 1 else f"{title} · {strings['page']} {number}",
                        description=intro,
                        url=url,
                        section=section,
                        alternates=self._section_alternates(section) if number == 1 else None,
                        noindex=number > 1,
                    ),
                    "listing": {
                        "kind": kind,
                        "title": title,
                        "intro": intro,
                        "documents": chunk,
                        "total": len(documents),
                    },
                    "pagination": {
                        "current": number,
                        "total": pages,
                        "has_previous": number > 1,
                        "has_next": number < pages,
                        "previous_url": (
                            language.url_for(section) if number == 2
                            else language.url_for(section, "page", str(number - 1)) if number > 2 else ""
                        ),
                        "next_url": language.url_for(section, "page", str(number + 1)) if number < pages else "",
                    },
                    "facets": self._facets(documents, kind),
                }
            )
            self._render("list.html", context, url)
            if number == 1:
                self._track_sitemap(
                    url, priority=0.8, changefreq="weekly", alternates=self._section_alternates(section)
                )

    def _facets(self, documents: Sequence[Document], kind: str) -> dict[str, list[str]]:
        """Filter values the client-side filter bar offers, derived from reality."""
        if kind != "writeup":
            return {"tags": sorted({tag for doc in documents for tag in doc.tags})}
        return {
            "tags": sorted({tag for doc in documents for tag in doc.tags}),
            "platforms": sorted({doc.platform for doc in documents if doc.platform}),
            "difficulties": sorted({doc.difficulty for doc in documents if doc.difficulty}),
            "systems": sorted({doc.os_name for doc in documents if doc.os_name}),
        }

    def _build_arsenal(self, lang: str) -> None:
        assert self.library is not None
        language = self.config.language(lang)
        strings = strings_for(lang)
        url = language.url_for("arsenal")
        grouped: list[dict[str, Any]] = []
        for category in self.library.arsenal_categories():
            entries = [entry for entry in self.library.arsenal if entry.category == category]
            grouped.append(
                {
                    "name": category,
                    "count": len(entries),
                    "entries": [
                        {
                            "slug": entry.slug,
                            "name": entry.name,
                            "url": entry.url,
                            "tags": entry.tags,
                            "license": entry.license,
                            "language": entry.language,
                            "featured": entry.featured,
                            "summary": entry.summary_for(lang),
                            "notes": Markup(entry.notes_for(lang)),
                        }
                        for entry in entries
                    ],
                }
            )
        context = self._base_context(lang)
        context.update(
            {
                "page": self._page(
                    lang=lang,
                    title=strings["arsenal_title"],
                    description=strings["arsenal_intro"],
                    url=url,
                    section="arsenal",
                    alternates=self._section_alternates("arsenal"),
                ),
                "categories": grouped,
                "total_tools": len(self.library.arsenal),
            }
        )
        self._render("arsenal.html", context, url)
        self._track_sitemap(url, priority=0.7, changefreq="weekly", alternates=self._section_alternates("arsenal"))

    def _build_tags(self, lang: str) -> None:
        assert self.library is not None
        language = self.config.language(lang)
        strings = strings_for(lang)
        tags = self.library.tag_list(lang)

        url = language.url_for("tags")
        context = self._base_context(lang)
        context.update(
            {
                "page": self._page(
                    lang=lang,
                    title=strings["tags_title"],
                    description=strings["tags_title"],
                    url=url,
                    section="tags",
                    alternates=self._section_alternates("tags"),
                ),
                "tags": [
                    {"name": info.name, "key": info.key, "count": info.count, "url": language.url_for("tags", info.key)}
                    for info in tags
                ],
            }
        )
        self._render("tags.html", context, url)
        self._track_sitemap(url, priority=0.4, alternates=self._section_alternates("tags"))

        for info in tags:
            tag_url = language.url_for("tags", info.key)
            tag_context = self._base_context(lang)
            tag_context.update(
                {
                    "page": self._page(
                        lang=lang,
                        title=f"{strings['tag_prefix']}: {info.name}",
                        description=f"{info.count} · {info.name}",
                        url=tag_url,
                        section="tags",
                    ),
                    "tag": {"name": info.name, "key": info.key, "count": info.count},
                    "listing": {
                        "kind": "tag",
                        "title": f"#{info.name}",
                        "intro": "",
                        "documents": sorted(info.documents, key=lambda doc: doc.date, reverse=True),
                        "total": info.count,
                    },
                    "pagination": {"current": 1, "total": 1, "has_previous": False, "has_next": False},
                    "facets": {"tags": []},
                }
            )
            self._render("tag.html", tag_context, tag_url)
            self._track_sitemap(tag_url, priority=0.3)

    def _build_search_page(self, lang: str) -> None:
        language = self.config.language(lang)
        strings = strings_for(lang)
        url = language.url_for("search")
        context = self._base_context(lang)
        context.update(
            {
                "page": self._page(
                    lang=lang,
                    title=strings["search_title"],
                    description=strings["search_hint"],
                    url=url,
                    section="search",
                    noindex=True,
                    alternates=self._section_alternates("search"),
                ),
            }
        )
        self._render("search.html", context, url)

    def _build_documents(self, lang: str) -> None:
        assert self.library is not None
        for document in self.library.by_lang(lang):
            template = {
                "post": "post.html",
                "writeup": "writeup.html",
                "page": "page.html",
            }[document.kind]
            alternates = self._alternates_for(document)
            context = self._base_context(lang)
            context.update(
                {
                    "page": self._page(
                        lang=lang,
                        title=document.title,
                        description=document.summary,
                        url=document.url,
                        section={"post": "blog", "writeup": "writeups", "page": document.slug}[document.kind],
                        kind="article" if document.kind != "page" else "website",
                        image=document.cover,
                        alternates=alternates,
                    ),
                    "doc": document,
                    "content": Markup(document.rendered.html),
                    "toc": document.toc_entries,
                    "structured_data": Markup(self._structured_data(document)),
                }
            )
            self._render(template, context, document.url)
            self._track_sitemap(
                document.url,
                lastmod=document.updated or document.date,
                priority=0.9 if document.featured else 0.6,
                changefreq="monthly",
                alternates=alternates if len(alternates) > 1 else None,
            )

    def _structured_data(self, document: Document) -> str:
        """schema.org JSON-LD.

        Emitted inside ``<script type="application/ld+json">``.  The JSON is
        escaped by the ``json`` filter's rules -- ``<``, ``>`` and ``&`` become
        unicode escapes -- so a title containing ``</script>`` cannot break out
        of the element.
        """
        if document.kind == "page":
            payload: dict[str, Any] = {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": document.title,
                "url": self.config.absolute(document.url),
                "inLanguage": self.config.language(document.lang).locale,
            }
        else:
            payload = {
                "@context": "https://schema.org",
                "@type": "TechArticle",
                "headline": document.title,
                "description": document.summary,
                "url": self.config.absolute(document.url),
                "datePublished": document.date.isoformat(),
                "dateModified": (document.updated or document.date).isoformat(),
                "inLanguage": self.config.language(document.lang).locale,
                "wordCount": document.word_count,
                "author": {"@type": "Person", "name": self.config.author, "url": self.config.base_url},
                "publisher": {"@type": "Person", "name": self.config.author},
                "mainEntityOfPage": {"@type": "WebPage", "@id": self.config.absolute(document.url)},
            }
            if document.tags:
                payload["keywords"] = ", ".join(document.tags)
            if document.cover:
                payload["image"] = self.config.absolute(document.cover)
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    # -- generated data --------------------------------------------------- #

    def _build_feeds(self, lang: str) -> None:
        assert self.library is not None
        language = self.config.language(lang)
        prefix = f"/{language.prefix}" if language.prefix else ""
        items = self.library.feed_items(lang)
        title = f"{self.config.title}"
        description = self.config.description.get(lang, "")

        rss_url = f"{prefix}/feed.xml"
        atom_url = f"{prefix}/atom.xml"
        json_url = f"{prefix}/feed.json"

        self.assets.write(
            rss_url,
            feeds_module.render_rss(self.config, items, lang=lang, feed_url=rss_url, title=title, description=description),
            record=False,
        )
        self.assets.write(
            atom_url,
            feeds_module.render_atom(self.config, items, lang=lang, feed_url=atom_url, title=title, description=description),
            record=False,
        )
        self.assets.write(
            json_url,
            feeds_module.render_json_feed(self.config, items, lang=lang, feed_url=json_url, title=title, description=description),
            record=False,
        )

    def _build_indexes(self, lang: str) -> None:
        assert self.library is not None
        documents = [doc for doc in self.library.by_lang(lang) if doc.kind != "page"]
        pages = self.library.pages(lang)
        self.assets.write(
            f"/search-{lang}.json",
            build_search_index(self.config, documents + pages, self.library.arsenal, lang=lang),
            record=False,
        )
        self.assets.write(
            f"/fs-{lang}.json",
            build_command_index(self.config, self.library, lang=lang),
            record=False,
        )

    def _build_404(self) -> None:
        lang = self.config.default_language
        language = self.config.language(lang)
        strings = strings_for(lang)
        context = self._base_context(lang)
        context.update(
            {
                "page": self._page(
                    lang=lang,
                    title=strings["notfound_title"],
                    description=strings["notfound_body"],
                    url="/404.html",
                    section="404",
                    noindex=True,
                ),
                "home_url": language.url_for(),
            }
        )
        html = self.engine.render("404.html", context)
        self.assets.write("/404.html", html, record=False)
        self.result.pages += 1

    def _build_root_files(self) -> None:
        config = self.config

        self.assets.write("/sitemap.xml", feeds_module.render_sitemap(config, self._sitemap), record=False)
        self.assets.write("/robots.txt", feeds_module.render_robots(config), record=False)
        self.assets.write("/.well-known/security.txt", feeds_module.render_security_txt(config), record=False)
        self.assets.write("/security.txt", feeds_module.render_security_txt(config), record=False)

        manifest = {
            "name": config.title,
            "short_name": config.handle,
            "description": config.description.get(config.default_language, ""),
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#05070a",
            "theme_color": "#05070a",
            "lang": config.default_language,
            "categories": ["technology", "education", "security"],
            "icons": [
                {"src": "/static/img/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "/static/img/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                {"src": "/static/img/icon-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            ],
        }
        self.assets.write("/site.webmanifest", json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", record=False)

        # Service worker: precache the shell, then serve stale-while-revalidate.
        precache = sorted(
            info.versioned_url
            for url, info in self.assets.manifest.items()
            if url.endswith((".css", ".js", ".woff2"))
        )
        sw_source_path = os.path.join(config.theme_path, "static", "js", "sw.template.js")
        if os.path.isfile(sw_source_path):
            with open(sw_source_path, "r", encoding="utf-8") as handle:
                template = handle.read()
            version = self.now.strftime("%Y%m%d%H%M%S")
            sw = template.replace("__PRECACHE__", json.dumps(precache, separators=(",", ":")))
            sw = sw.replace("__VERSION__", version)
            self.assets.write("/sw.js", sw, record=False)

        if config.base_url and "github.io" not in config.base_url:
            host = config.base_url.split("://", 1)[-1].strip("/")
            self.assets.write("/CNAME", host + "\n", record=False)

    # -- reporting -------------------------------------------------------- #

    def report(self, stream=sys.stdout) -> None:
        result = self.result
        write = lambda text: print(text, file=stream)  # noqa: E731
        write("")
        write(f"  documentos   {result.documents}")
        write(f"  páginas      {result.pages}")
        write(f"  assets       {result.assets}")
        write(f"  tiempo       {result.duration * 1000:.0f} ms")
        write("")
        for line in result.summary_lines:
            write(f"  {line}")
        if result.warnings:
            write("")
            for warning in result.warnings:
                write(f"  aviso: {warning}")
        if result.budget_problems:
            write("")
            write("  PRESUPUESTO EXCEDIDO:")
            for problem in result.budget_problems:
                write(f"    - {problem}")
        write("")


def build(
    config_path: str = "site.json",
    *,
    include_drafts: bool = False,
    minify: bool = True,
    base_url: str | None = None,
) -> tuple[Builder, BuildResult]:
    config = load_config(config_path)
    builder = Builder(config, include_drafts=include_drafts, minify=minify, base_url_override=base_url)
    result = builder.build()
    return builder, result
