"""
Site configuration: loading, validation and derived values.

Everything the generator needs to know that is not content lives in
``site.json`` at the repository root.  It is plain JSON on purpose -- the
standard library parses it, an editor validates it, and there is no chance of
a config file quietly executing code at build time.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

__all__ = ["SiteConfig", "load_config", "ConfigError"]


class ConfigError(Exception):
    """Raised when site.json is missing something the build depends on."""


DEFAULT_BUDGETS: dict[str, int] = {
    # Bytes. Enforced by `python3 build.py --check`; see tools/ssg/check.py.
    "js_gzip_total": 60 * 1024,
    "css_gzip_total": 45 * 1024,
    "html_gzip_page": 30 * 1024,
    "media_file_max": 2 * 1024 * 1024,
    "media_total_max": 25 * 1024 * 1024,
    "font_total": 220 * 1024,
}


@dataclass
class LanguageConfig:
    code: str
    name: str
    native_name: str
    prefix: str            # URL prefix: "" for the default language, "en" otherwise
    locale: str
    date_format: str
    is_default: bool = False

    def url_for(self, *parts: str) -> str:
        segments = [segment.strip("/") for segment in parts if segment and segment.strip("/")]
        joined = "/".join(segments)
        if self.prefix:
            joined = f"{self.prefix}/{joined}" if joined else self.prefix
        return "/" + joined + "/" if joined else "/"


@dataclass
class SiteConfig:
    # identity
    title: str
    handle: str
    tagline: dict[str, str]
    description: dict[str, str]
    author: str
    base_url: str

    # languages
    languages: list[LanguageConfig]
    default_language: str

    # presentation
    default_theme: str = "phosphor"
    themes: list[str] = field(default_factory=lambda: ["phosphor", "amber", "ice", "redteam"])
    posts_per_page: int = 12
    excerpt_length: int = 240
    words_per_minute: int = 220

    # contact / identity proofs
    email: str = ""
    pgp_fingerprint: str = ""
    pgp_key_path: str = ""
    social: list[dict[str, str]] = field(default_factory=list)

    # build
    source_root: str = "."
    content_dir: str = "content"
    theme_dir: str = "theme"
    output_dir: str = "dist"
    static_prefix: str = "/static"
    budgets: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_BUDGETS))

    # security
    csp: dict[str, str] = field(default_factory=dict)
    permissions_policy: str = ""

    # feeds
    feed_items: int = 30
    build_timestamp: str = ""

    # -- derived ---------------------------------------------------------- #

    def language(self, code: str) -> LanguageConfig:
        for entry in self.languages:
            if entry.code == code:
                return entry
        raise ConfigError(f"unknown language {code!r}; configured: {[l.code for l in self.languages]}")

    @property
    def default_lang(self) -> LanguageConfig:
        return self.language(self.default_language)

    @property
    def language_codes(self) -> list[str]:
        return [entry.code for entry in self.languages]

    def path(self, *parts: str) -> str:
        return os.path.join(self.source_root, *parts)

    @property
    def content_path(self) -> str:
        return self.path(self.content_dir)

    @property
    def theme_path(self) -> str:
        return self.path(self.theme_dir)

    @property
    def output_path(self) -> str:
        return self.path(self.output_dir)

    def absolute(self, url: str) -> str:
        """Turn a root-relative URL into a fully qualified one for feeds/OG."""
        if url.startswith(("http://", "https://")):
            return url
        return self.base_url.rstrip("/") + "/" + url.lstrip("/")

    def csp_header(self) -> str:
        """Serialise the CSP directives in a stable order."""
        directives = self.csp or DEFAULT_CSP
        return "; ".join(f"{key} {value}".strip() for key, value in directives.items())

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "handle": self.handle,
            "author": self.author,
            "base_url": self.base_url,
            "default_theme": self.default_theme,
            "themes": self.themes,
            "languages": [
                {"code": entry.code, "name": entry.name, "native": entry.native_name, "prefix": entry.prefix}
                for entry in self.languages
            ],
        }


# A deliberately tight policy.  Everything the page loads comes from this
# origin; there is no third party to allow.  `style-src` keeps 'unsafe-inline'
# because the critical-CSS inlining and the CSS custom properties written by
# the theme switcher both need it, and a style injection on an origin with no
# script execution is a defacement risk rather than a code-execution one.
DEFAULT_CSP: dict[str, str] = {
    "default-src": "'none'",
    "base-uri": "'none'",
    "script-src": "'self'",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": "'self' data:",
    "media-src": "'self'",
    "font-src": "'self'",
    "connect-src": "'self'",
    "manifest-src": "'self'",
    "form-action": "'none'",
    "frame-ancestors": "'none'",
    "frame-src": "'none'",
    "object-src": "'none'",
    "worker-src": "'self'",
    "upgrade-insecure-requests": "",
}

DEFAULT_PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), "
    "fullscreen=(self), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), "
    "midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), "
    "screen-wake-lock=(), usb=(), xr-spatial-tracking=()"
)


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ConfigError(f"site.json is missing the required key {key!r}")
    return data[key]


def load_config(path: str = "site.json", *, source_root: str | None = None) -> SiteConfig:
    """Read and validate ``site.json``."""
    root = source_root or os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isfile(path):
        raise ConfigError(f"configuration file not found: {path}")

    with open(path, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as error:
            raise ConfigError(f"{path} is not valid JSON: {error}") from error

    raw_languages = _require(data, "languages")
    if not isinstance(raw_languages, list) or not raw_languages:
        raise ConfigError("site.json 'languages' must be a non-empty list")

    default_language = data.get("default_language") or raw_languages[0].get("code")
    languages: list[LanguageConfig] = []
    for entry in raw_languages:
        code = _require(entry, "code")
        is_default = code == default_language
        languages.append(
            LanguageConfig(
                code=code,
                name=entry.get("name", code.upper()),
                native_name=entry.get("native_name", entry.get("name", code.upper())),
                prefix="" if is_default else entry.get("prefix", code),
                locale=entry.get("locale", code),
                date_format=entry.get("date_format", "%d %b %Y"),
                is_default=is_default,
            )
        )

    if not any(entry.is_default for entry in languages):
        raise ConfigError(f"default_language {default_language!r} is not present in 'languages'")

    base_url = str(_require(data, "base_url")).rstrip("/")
    if not base_url.startswith("https://"):
        raise ConfigError(f"base_url must be an https URL, got {base_url!r}")

    budgets = dict(DEFAULT_BUDGETS)
    budgets.update({key: int(value) for key, value in (data.get("budgets") or {}).items()})

    csp = dict(DEFAULT_CSP)
    csp.update(data.get("csp") or {})

    config = SiteConfig(
        title=_require(data, "title"),
        handle=data.get("handle", data.get("title", "")),
        tagline=_as_lang_map(data.get("tagline", ""), languages),
        description=_as_lang_map(data.get("description", ""), languages),
        author=data.get("author", data.get("handle", "")),
        base_url=base_url,
        languages=languages,
        default_language=default_language,
        default_theme=data.get("default_theme", "phosphor"),
        themes=data.get("themes", ["phosphor", "amber", "ice", "redteam"]),
        posts_per_page=int(data.get("posts_per_page", 12)),
        excerpt_length=int(data.get("excerpt_length", 240)),
        words_per_minute=int(data.get("words_per_minute", 220)),
        email=data.get("email", ""),
        pgp_fingerprint=data.get("pgp_fingerprint", ""),
        pgp_key_path=data.get("pgp_key_path", ""),
        social=data.get("social", []),
        source_root=root,
        content_dir=data.get("content_dir", "content"),
        theme_dir=data.get("theme_dir", "theme"),
        output_dir=data.get("output_dir", "dist"),
        static_prefix=data.get("static_prefix", "/static"),
        budgets=budgets,
        csp=csp,
        permissions_policy=data.get("permissions_policy", DEFAULT_PERMISSIONS_POLICY),
        feed_items=int(data.get("feed_items", 30)),
    )
    return config


def _as_lang_map(value: Any, languages: list[LanguageConfig]) -> dict[str, str]:
    """Accept either a plain string or a per-language object."""
    if isinstance(value, dict):
        return {entry.code: str(value.get(entry.code, value.get("es", ""))) for entry in languages}
    return {entry.code: str(value) for entry in languages}
