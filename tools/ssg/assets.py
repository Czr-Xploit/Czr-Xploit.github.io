"""
Static asset pipeline: copying, cache-busting, CSS bundling and budget checks.

Deliberate omissions
--------------------
* **No JavaScript minifier.**  Writing a correct one is a parser problem, and
  writing an incorrect one is a debugging nightmare that surfaces in
  production.  GitHub Pages already serves everything gzipped, and the byte
  budget is measured post-gzip, where minification buys very little.  The JS
  that ships is the JS in the repo -- readable, auditable, diffable.
* **No filename hashing.**  Renaming files means rewriting every reference
  inside CSS (``url()``), JS (dynamic ``import``) and the service worker.  A
  ``?v=`` query string derived from the file's own content hash achieves the
  same invalidation with none of the rewriting, and GitHub Pages honours it.
"""

from __future__ import annotations

import hashlib
import gzip
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = ["AssetPipeline", "AssetInfo", "minify_css", "gzip_size", "human_bytes"]


# Files we never publish even if they land in the theme directory.
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db", ".gitkeep", ".gitignore"}
EXCLUDED_SUFFIXES = (".swp", ".swo", "~", ".orig", ".rej", ".bak", ".psd", ".xcf", ".ai")

TEXT_SUFFIXES = {".css", ".js", ".mjs", ".json", ".svg", ".txt", ".xml", ".webmanifest", ".map"}

MEDIA_SUFFIXES = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".avif", ".mp4", ".webm", ".mov", ".apng"}

FONT_SUFFIXES = {".woff2", ".woff", ".ttf", ".otf"}


def human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size} B"


def gzip_size(data: bytes, level: int = 9) -> int:
    """Compressed size as the browser would receive it."""
    return len(gzip.compress(data, compresslevel=level, mtime=0))


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #

_CSS_COMMENT_RE = re.compile(r"/\*(?!!)[\s\S]*?\*/")
_CSS_WS_RE = re.compile(r"\s+")
_CSS_AROUND_RE = re.compile(r"\s*([{}:;,>~+])\s*")
_CSS_STRING_RE = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")


def minify_css(source: str) -> str:
    """Conservative CSS minification that leaves strings and URLs untouched.

    Strings are lifted out before any whitespace collapsing so that a selector
    like ``[data-x=" a "]`` or a ``content: "  "`` declaration keeps its
    meaningful spaces.
    """
    placeholders: list[str] = []

    def stash(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"\x00{len(placeholders) - 1}\x00"

    text = _CSS_STRING_RE.sub(stash, source)
    text = _CSS_COMMENT_RE.sub("", text)
    text = _CSS_WS_RE.sub(" ", text)
    text = _CSS_AROUND_RE.sub(r"\1", text)
    text = text.replace(";}", "}")
    # `and(` / `not(` are invalid in a media query; restore the separating space.
    # The negative lookbehind is load-bearing: `:not(` in a *selector* must NOT
    # gain a space -- `:not ([hidden])` is an invalid selector, so the whole rule
    # is dropped by the parser. That silently disabled every `:not()` rule in the
    # stylesheet, which is how the command palette ended up unable to open.
    text = re.sub(r"(?<![:\w-])\b(and|or|not)\(", r"\1 (", text)
    text = re.sub(r"@media\(", "@media (", text)
    text = text.strip()

    def restore(match: re.Match[str]) -> str:
        return placeholders[int(match.group(1))]

    return re.sub(r"\x00(\d+)\x00", restore, text)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #

@dataclass
class AssetInfo:
    url: str
    source: str
    output: str
    size: int
    gzipped: int
    digest: str

    @property
    def versioned_url(self) -> str:
        return f"{self.url}?v={self.digest[:10]}"


@dataclass
class AssetReport:
    assets: dict[str, AssetInfo] = field(default_factory=dict)
    css_bytes: int = 0
    css_gzip: int = 0
    js_bytes: int = 0
    js_gzip: int = 0
    media_bytes: int = 0
    media_files: list[tuple[str, int]] = field(default_factory=list)
    font_bytes: int = 0
    copied: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "copied": self.copied,
            "css_gzip": self.css_gzip,
            "js_gzip": self.js_gzip,
            "media_bytes": self.media_bytes,
            "font_bytes": self.font_bytes,
        }


class AssetPipeline:
    """Copies ``theme/static`` into the output tree and measures what it wrote."""

    def __init__(self, config, *, minify: bool = True) -> None:
        self.config = config
        self.minify = minify
        self.report = AssetReport()
        self.manifest: dict[str, AssetInfo] = {}

    # -- helpers ---------------------------------------------------------- #

    @staticmethod
    def _should_skip(filename: str) -> bool:
        if filename in EXCLUDED_NAMES or filename.startswith("."):
            return True
        return filename.endswith(EXCLUDED_SUFFIXES)

    def _record(self, url: str, source: str, output: str, data: bytes) -> AssetInfo:
        digest = hashlib.sha256(data).hexdigest()
        suffix = os.path.splitext(output)[1].lower()
        compressed = gzip_size(data) if suffix in TEXT_SUFFIXES else len(data)
        info = AssetInfo(url=url, source=source, output=output, size=len(data), gzipped=compressed, digest=digest)
        self.manifest[url] = info

        if suffix == ".css":
            self.report.css_bytes += info.size
            self.report.css_gzip += info.gzipped
        elif suffix in (".js", ".mjs"):
            self.report.js_bytes += info.size
            self.report.js_gzip += info.gzipped
        elif suffix in MEDIA_SUFFIXES:
            self.report.media_bytes += info.size
            self.report.media_files.append((url, info.size))
        elif suffix in FONT_SUFFIXES:
            self.report.font_bytes += info.size
        return info

    # -- public ----------------------------------------------------------- #

    def copy_static(self) -> AssetReport:
        source_root = os.path.join(self.config.theme_path, "static")
        target_root = os.path.join(self.config.output_path, self.config.static_prefix.strip("/"))

        if not os.path.isdir(source_root):
            return self.report

        for dirpath, dirnames, filenames in os.walk(source_root):
            dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
            for filename in sorted(filenames):
                if self._should_skip(filename):
                    continue
                source = os.path.join(dirpath, filename)
                relative = os.path.relpath(source, source_root)
                target = os.path.join(target_root, relative)
                os.makedirs(os.path.dirname(target), exist_ok=True)

                suffix = os.path.splitext(filename)[1].lower()
                if suffix == ".css" and self.minify:
                    with open(source, "r", encoding="utf-8") as handle:
                        data = minify_css(handle.read()).encode("utf-8")
                    with open(target, "wb") as out:
                        out.write(data)
                else:
                    shutil.copy2(source, target)
                    with open(target, "rb") as handle:
                        data = handle.read()

                url = "/" + os.path.join(self.config.static_prefix.strip("/"), relative).replace(os.sep, "/")
                self._record(url, source, target, data)
                self.report.copied += 1

        return self.report

    def write(self, relative_url: str, content: str | bytes, *, record: bool = True) -> AssetInfo:
        """Write a generated file into the output tree and account for it."""
        data = content.encode("utf-8") if isinstance(content, str) else content
        target = os.path.join(self.config.output_path, relative_url.strip("/").replace("/", os.sep))
        os.makedirs(os.path.dirname(target) or self.config.output_path, exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
        url = "/" + relative_url.strip("/")
        if record:
            return self._record(url, "<generated>", target, data)
        digest = hashlib.sha256(data).hexdigest()
        return AssetInfo(url=url, source="<generated>", output=target, size=len(data), gzipped=len(data), digest=digest)

    def url_for(self, path: str) -> str:
        """Cache-busted URL for an asset, or the plain path when unknown."""
        key = path if path.startswith("/") else "/" + path
        info = self.manifest.get(key)
        return info.versioned_url if info else key

    def bundle_css(self, order: Iterable[str], *, output: str) -> AssetInfo:
        """Concatenate stylesheets in a fixed order into one request."""
        chunks: list[str] = []
        for name in order:
            path = os.path.join(self.config.theme_path, "css", name)
            if not os.path.isfile(path):
                raise FileNotFoundError(f"stylesheet not found: {path}")
            with open(path, "r", encoding="utf-8") as handle:
                chunks.append(f"/* {name} */\n" + handle.read())
        combined = "\n".join(chunks)
        if self.minify:
            combined = minify_css(combined)
        return self.write(output, combined)

    def read_css(self, name: str) -> str:
        path = os.path.join(self.config.theme_path, "static", "css", name)
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        return minify_css(text) if self.minify else text

    # -- budgets ---------------------------------------------------------- #

    def budget_violations(self) -> list[str]:
        """Return human-readable budget failures. Empty list means we are fine."""
        budgets = self.config.budgets
        problems: list[str] = []

        if self.report.js_gzip > budgets["js_gzip_total"]:
            problems.append(
                f"JS gzip {human_bytes(self.report.js_gzip)} exceeds budget {human_bytes(budgets['js_gzip_total'])}"
            )
        if self.report.css_gzip > budgets["css_gzip_total"]:
            problems.append(
                f"CSS gzip {human_bytes(self.report.css_gzip)} exceeds budget {human_bytes(budgets['css_gzip_total'])}"
            )
        if self.report.media_bytes > budgets["media_total_max"]:
            problems.append(
                f"media total {human_bytes(self.report.media_bytes)} exceeds budget {human_bytes(budgets['media_total_max'])}"
            )
        if self.report.font_bytes > budgets["font_total"]:
            problems.append(
                f"fonts {human_bytes(self.report.font_bytes)} exceed budget {human_bytes(budgets['font_total'])}"
            )
        for url, size in self.report.media_files:
            if size > budgets["media_file_max"]:
                problems.append(
                    f"{url} is {human_bytes(size)}, over the {human_bytes(budgets['media_file_max'])} per-file cap"
                )
        return problems

    def summary_lines(self) -> list[str]:
        budgets = self.config.budgets
        return [
            f"CSS   {human_bytes(self.report.css_gzip):>10} gz  / {human_bytes(budgets['css_gzip_total'])}",
            f"JS    {human_bytes(self.report.js_gzip):>10} gz  / {human_bytes(budgets['js_gzip_total'])}",
            f"Media {human_bytes(self.report.media_bytes):>10}     / {human_bytes(budgets['media_total_max'])}",
            f"Fonts {human_bytes(self.report.font_bytes):>10}     / {human_bytes(budgets['font_total'])}",
        ]
