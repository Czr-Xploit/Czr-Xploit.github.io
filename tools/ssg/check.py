"""
Post-build verification.

This is the machine-checkable half of the pre-deploy audit; the judgement half
lives in the `site-sentinel` agent.  Everything here is deterministic and
either passes or fails -- no heuristics that produce "maybe" findings, because
a verifier that cries wolf gets ignored, and an ignored verifier is worse than
none.

Every finding carries: a severity, the check that produced it, a message that
states the observed value, and where to look.
"""

from __future__ import annotations

import gzip
import html
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

__all__ = ["Finding", "run_checks"]


SEVERITIES = ("BLOCKER", "HIGH", "MEDIUM", "LOW")


@dataclass
class Finding:
    severity: str
    check: str
    message: str
    location: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "check": self.check,
            "message": self.message,
            "location": self.location,
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _walk(root: str, suffixes: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(dirnames)
        for filename in sorted(filenames):
            if filename.endswith(suffixes):
                found.append(os.path.join(dirpath, filename))
    return found


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _relative(path: str, root: str) -> str:
    return os.path.relpath(path, root)


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #

_EXTERNAL_SUBRESOURCE_RE = re.compile(
    r"""<(?:script|link|img|source|video|audio|iframe|embed|object|track)\b[^>]*?"""
    r"""\b(?:src|href|srcset|data)\s*=\s*["'](?P<url>[^"']+)["']""",
    re.IGNORECASE,
)

_CSS_EXTERNAL_RE = re.compile(r"""(?:url\(\s*["']?|@import\s+["'])(?P<url>(?:https?:)?//[^"')\s]+)""", re.IGNORECASE)


def check_no_external_subresources(root: str) -> list[Finding]:
    """Nothing the browser loads may come from another origin."""
    findings: list[Finding] = []
    for path in _walk(root, (".html",)):
        content = _read(path)
        for match in _EXTERNAL_SUBRESOURCE_RE.finditer(content):
            url = match.group("url").strip()
            if url.startswith(("http://", "https://", "//")):
                # A <link rel="alternate"> to our own absolute feed URL is fine.
                if "rel=\"alternate\"" in match.group(0) or "rel='alternate'" in match.group(0):
                    continue
                if "rel=\"canonical\"" in match.group(0):
                    continue
                findings.append(
                    Finding(
                        "BLOCKER",
                        "supply-chain",
                        f"page loads a subresource from another origin: {url}",
                        _relative(path, root),
                    )
                )
    for path in _walk(root, (".css",)):
        content = _read(path)
        for match in _CSS_EXTERNAL_RE.finditer(content):
            findings.append(
                Finding("BLOCKER", "supply-chain", f"stylesheet references {match.group('url')}", _relative(path, root))
            )
    return findings


def check_inline_scripts_and_handlers(root: str) -> list[Finding]:
    """The CSP forbids inline execution; verify nothing generated any."""
    findings: list[Finding] = []
    handler_re = re.compile(r"\son[a-z]+\s*=\s*[\"']", re.IGNORECASE)
    inline_script_re = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*type=[\"'](?:application/(?:ld\+json|json)|importmap)[\"'])[^>]*>", re.IGNORECASE)
    js_url_re = re.compile(r"""(?:href|src|action)\s*=\s*["']\s*javascript:""", re.IGNORECASE)

    for path in _walk(root, (".html",)):
        content = _read(path)
        location = _relative(path, root)
        for match in inline_script_re.finditer(content):
            findings.append(Finding("BLOCKER", "csp", "inline <script> would be blocked by the CSP", f"{location}: {match.group(0)[:70]}"))
        for match in handler_re.finditer(content):
            attribute = match.group(0).strip().split("=", 1)[0]
            findings.append(Finding("BLOCKER", "csp", f"inline event handler '{attribute}' would be blocked", location))
        if js_url_re.search(content):
            findings.append(Finding("BLOCKER", "csp", "javascript: URL present in output", location))
    return findings


def check_csp_present(root: str, expected: str) -> list[Finding]:
    findings: list[Finding] = []
    pattern = re.compile(r'<meta[^>]+http-equiv=["\']Content-Security-Policy["\'][^>]*content=["\'](?P<policy>[^"\']+)["\']', re.IGNORECASE)
    for path in _walk(root, (".html",)):
        content = _read(path)
        match = pattern.search(content)
        location = _relative(path, root)
        if match is None:
            findings.append(Finding("HIGH", "csp", "page has no Content-Security-Policy meta tag", location))
            continue
        # The attribute is HTML-escaped on the way out, so every apostrophe in the
        # policy arrives here as &#x27;. Comparing against "'unsafe-inline'"
        # without decoding first silently matches nothing -- the check would pass
        # on a policy that actually allows inline script.
        policy = html.unescape(match.group("policy"))
        if "script-src" not in policy:
            findings.append(Finding("HIGH", "csp", "policy has no script-src directive", location))
        if "'unsafe-eval'" in policy:
            findings.append(Finding("BLOCKER", "csp", "policy allows 'unsafe-eval'", location))
        if re.search(r"script-src[^;]*'unsafe-inline'", policy):
            findings.append(Finding("BLOCKER", "csp", "policy allows inline scripts", location))
    return findings


_CODE_REGION_RE = re.compile(
    r"<pre\b[\s\S]*?</pre>|<code\b[\s\S]*?</code>|<script[^>]*>[\s\S]*?</script>",
    re.IGNORECASE,
)


def _strip_code_regions(content: str) -> str:
    """Blank out code samples before link scanning.

    An article about CSP legitimately contains ``<script src="app.js">`` inside a
    code fence. That is a quoted example, not a subresource, and reporting it as a
    broken link is exactly the kind of false positive that trains people to ignore
    the checker. Replace with spaces rather than deleting so offsets stay usable.
    """
    return _CODE_REGION_RE.sub(lambda match: " " * len(match.group(0)), content)


def check_internal_links(root: str) -> list[Finding]:
    """Every internal href must resolve to a file or a fragment that exists."""
    findings: list[Finding] = []
    pages = _walk(root, (".html",))

    anchors: dict[str, set[str]] = {}
    for path in pages:
        content = _read(path)
        ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', content))
        anchors[path] = ids

    def resolve(url: str, from_path: str) -> str | None:
        parsed = urlparse(url)
        if parsed.scheme or parsed.netloc:
            return None
        path = unquote(parsed.path)
        if not path:
            return from_path
        if path.startswith("/"):
            candidate = os.path.join(root, path.lstrip("/"))
        else:
            candidate = os.path.normpath(os.path.join(os.path.dirname(from_path), path))
        if os.path.isdir(candidate):
            candidate = os.path.join(candidate, "index.html")
        return candidate

    href_re = re.compile(r'\b(?:href|src)=["\'](?P<url>[^"\'#][^"\']*|#[^"\']*)["\']')

    for path in pages:
        content = _strip_code_regions(_read(path))
        location = _relative(path, root)
        for match in href_re.finditer(content):
            url = match.group("url").strip()
            if url.startswith(("http://", "https://", "mailto:", "tel:", "data:", "//")):
                continue
            base, _, fragment = url.partition("#")
            target = resolve(base or "", path)
            if target is None:
                continue
            clean_target = target.split("?")[0]
            if not os.path.exists(clean_target):
                findings.append(Finding("HIGH", "links", f"broken internal link: {url}", location))
                continue
            if fragment and clean_target.endswith(".html"):
                if fragment not in anchors.get(clean_target, set()):
                    findings.append(
                        Finding("MEDIUM", "links", f"fragment #{fragment} not found in {_relative(clean_target, root)}", location)
                    )
    return findings


def check_bilingual_pairs(library) -> list[Finding]:
    findings: list[Finding] = []
    if library is None:
        return findings
    groups: dict[tuple[str, str], list] = {}
    for document in library.documents:
        groups.setdefault((document.kind, document.translation_key), []).append(document)
    expected = set(library.config.language_codes)
    for (kind, key), group in sorted(groups.items()):
        present = {document.lang for document in group}
        missing = expected - present
        if missing:
            findings.append(
                Finding(
                    "LOW",
                    "i18n",
                    f"translation_key '{key}' ({kind}) has no {', '.join(sorted(missing))} version",
                    group[0].source_path,
                )
            )
        if len(present) != len(group):
            findings.append(
                Finding("HIGH", "i18n", f"translation_key '{key}' has two documents in the same language", group[0].source_path)
            )
    return findings


def check_html_structure(root: str) -> list[Finding]:
    findings: list[Finding] = []
    for path in _walk(root, (".html",)):
        content = _read(path)
        location = _relative(path, root)
        if not re.search(r"<html[^>]+\blang=", content, re.IGNORECASE):
            findings.append(Finding("MEDIUM", "a11y", "<html> has no lang attribute", location))
        if "<title>" not in content.lower():
            findings.append(Finding("HIGH", "seo", "page has no <title>", location))
        if not re.search(r'<meta[^>]+name=["\']description["\']', content, re.IGNORECASE):
            findings.append(Finding("LOW", "seo", "page has no meta description", location))
        if not re.search(r'<meta[^>]+name=["\']viewport["\']', content, re.IGNORECASE):
            findings.append(Finding("HIGH", "a11y", "page has no viewport meta tag", location))
        # Images must be measurable to avoid layout shift.
        for match in re.finditer(r"<img\b[^>]*>", content, re.IGNORECASE):
            tag = match.group(0)
            if "alt=" not in tag.lower():
                findings.append(Finding("MEDIUM", "a11y", f"<img> without alt: {tag[:80]}", location))
        # target=_blank without rel=noopener is a tabnabbing vector.
        for match in re.finditer(r"<a\b[^>]*target=[\"']_blank[\"'][^>]*>", content, re.IGNORECASE):
            if "noopener" not in match.group(0).lower():
                findings.append(Finding("MEDIUM", "security", "target=_blank without rel=noopener", location))
    return findings


def check_heading_order(root: str) -> list[Finding]:
    findings: list[Finding] = []
    for path in _walk(root, (".html",)):
        content = _read(path)
        location = _relative(path, root)
        levels = [int(match.group(1)) for match in re.finditer(r"<h([1-6])\b", content, re.IGNORECASE)]
        if not levels:
            continue
        if levels.count(1) > 1:
            findings.append(Finding("LOW", "a11y", f"page has {levels.count(1)} <h1> elements", location))
        previous = levels[0]
        for level in levels[1:]:
            if level > previous + 1:
                findings.append(
                    Finding("LOW", "a11y", f"heading level jumps from h{previous} to h{level}", location)
                )
                break
            previous = level
    return findings


def check_secrets(root: str, repo_root: str) -> list[Finding]:
    """Look for material that should never have been published."""
    patterns: list[tuple[str, str, str]] = [
        ("private-key", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY", "BLOCKER"),
        ("aws-key", r"\bAKIA[0-9A-Z]{16}\b", "BLOCKER"),
        ("github-token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "BLOCKER"),
        ("slack-token", r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b", "BLOCKER"),
        ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "HIGH"),
        ("home-path", r"/home/(?!kali\b)[a-z][a-z0-9_-]{2,}/", "LOW"),
        ("private-ip", r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b", "LOW"),
    ]
    findings: list[Finding] = []
    targets = _walk(root, (".html", ".json", ".xml", ".txt", ".js", ".css"))
    for path in targets:
        content = _read(path)
        location = _relative(path, root)
        for name, pattern, severity in patterns:
            match = re.search(pattern, content)
            if match:
                sample = match.group(0)[:40]
                findings.append(Finding(severity, f"opsec/{name}", f"possible {name} in output: {sample}", location))
    return findings


def check_required_files(root: str) -> list[Finding]:
    required = [
        (".nojekyll", "BLOCKER", "GitHub Pages will run Jekyll and drop underscore paths"),
        ("404.html", "HIGH", "no custom 404 page"),
        ("sitemap.xml", "MEDIUM", "no sitemap"),
        ("robots.txt", "LOW", "no robots.txt"),
        ("feed.xml", "MEDIUM", "no RSS feed"),
        ("index.html", "BLOCKER", "no home page was generated"),
    ]
    findings: list[Finding] = []
    for name, severity, message in required:
        if not os.path.exists(os.path.join(root, name)):
            findings.append(Finding(severity, "output", f"{message} ({name} missing)", root))
    return findings


def check_feeds_parse(root: str) -> list[Finding]:
    """A feed that does not parse is a feed nobody receives."""
    import xml.etree.ElementTree as ElementTree

    findings: list[Finding] = []
    for path in _walk(root, (".xml",)):
        try:
            ElementTree.parse(path)
        except ElementTree.ParseError as error:
            findings.append(Finding("HIGH", "feeds", f"XML does not parse: {error}", _relative(path, root)))
    for path in _walk(root, (".json",)):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                json.load(handle)
        except json.JSONDecodeError as error:
            findings.append(Finding("HIGH", "feeds", f"JSON does not parse: {error}", _relative(path, root)))
    return findings


def check_page_weight(root: str, budget: int) -> list[Finding]:
    findings: list[Finding] = []
    for path in _walk(root, (".html",)):
        with open(path, "rb") as handle:
            data = handle.read()
        compressed = len(gzip.compress(data, compresslevel=9, mtime=0))
        if compressed > budget:
            findings.append(
                Finding(
                    "MEDIUM",
                    "performance",
                    f"page is {compressed / 1024:.1f} KB gzipped, over the {budget / 1024:.0f} KB budget",
                    _relative(path, root),
                )
            )
    return findings


# One synchronous script is permitted in <head>: the anti-flash theme bootstrap.
# It has to run before first paint, and the CSP forbids inlining it, so there is
# no non-blocking spelling of this. The exemption is capped by size -- if the
# file grows past the cap it stops being a negligible cost and gets reported.
RENDER_BLOCKING_ALLOWLIST = {"theme-boot.js": 2048}


def check_render_blocking(root: str) -> list[Finding]:
    findings: list[Finding] = []
    script_re = re.compile(
        r"<script\b(?![^>]*\b(?:defer|async|type=[\"']module[\"']|type=[\"']application/))[^>]*\bsrc=[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    )
    for path in _walk(root, (".html",)):
        content = _read(path)
        for match in script_re.finditer(content):
            url = match.group(1).split("?")[0]
            name = os.path.basename(url)
            cap = RENDER_BLOCKING_ALLOWLIST.get(name)
            if cap is not None:
                target = os.path.join(root, url.lstrip("/"))
                size = os.path.getsize(target) if os.path.exists(target) else 0
                if size <= cap:
                    continue
                findings.append(
                    Finding(
                        "MEDIUM",
                        "performance",
                        f"{name} is render-blocking by design but has grown to {size} B (cap {cap} B)",
                        _relative(path, root),
                    )
                )
                continue
            findings.append(
                Finding("MEDIUM", "performance", f"render-blocking <script src={url}> without defer/async/module", _relative(path, root))
            )
    return findings


def check_stdlib_only(repo_root: str) -> list[Finding]:
    """The generator must import nothing outside the standard library."""
    import sys

    findings: list[Finding] = []
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    if not stdlib:
        return findings

    local_packages = {"tools", "ssg"}
    import_re = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)|import\s+([A-Za-z_][\w.]*))", re.MULTILINE)

    for path in _walk(os.path.join(repo_root, "tools"), (".py",)) + [os.path.join(repo_root, "build.py")]:
        if not os.path.exists(path):
            continue
        content = _read(path)
        for match in import_re.finditer(content):
            module = (match.group(1) or match.group(2) or "").split(".")[0]
            if not module or module.startswith("."):
                continue
            if module in stdlib or module in local_packages or module == "__future__":
                continue
            findings.append(
                Finding("BLOCKER", "supply-chain", f"generator imports non-stdlib module '{module}'", _relative(path, repo_root))
            )

    for lockfile in ("requirements.txt", "package.json", "package-lock.json", "Pipfile", "poetry.lock", "pyproject.toml"):
        candidate = os.path.join(repo_root, lockfile)
        if os.path.exists(candidate):
            findings.append(
                Finding("HIGH", "supply-chain", f"{lockfile} exists; the project is meant to have no dependencies", lockfile)
            )
    return findings


def check_search_index(root: str) -> list[Finding]:
    findings: list[Finding] = []
    for path in _walk(root, (".json",)):
        name = os.path.basename(path)
        if not name.startswith("search-"):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            try:
                payload = json.load(handle)
            except json.JSONDecodeError:
                continue
        if not payload.get("docs"):
            findings.append(Finding("MEDIUM", "search", "search index contains no documents", _relative(path, root)))
        size = os.path.getsize(path)
        if size > 512 * 1024:
            findings.append(
                Finding("LOW", "search", f"search index is {size / 1024:.0f} KB; consider trimming body text", _relative(path, root))
            )
    return findings


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

def run_checks(config, builder=None) -> list[Finding]:
    root = config.output_path
    repo_root = config.source_root
    library = getattr(builder, "library", None)

    findings: list[Finding] = []
    findings += check_required_files(root)
    findings += check_stdlib_only(repo_root)
    findings += check_no_external_subresources(root)
    findings += check_inline_scripts_and_handlers(root)
    findings += check_csp_present(root, config.csp_header())
    findings += check_internal_links(root)
    findings += check_html_structure(root)
    findings += check_heading_order(root)
    findings += check_feeds_parse(root)
    findings += check_page_weight(root, config.budgets["html_gzip_page"])
    findings += check_render_blocking(root)
    findings += check_secrets(root, repo_root)
    findings += check_search_index(root)
    findings += check_bilingual_pairs(library)

    order = {severity: index for index, severity in enumerate(SEVERITIES)}
    findings.sort(key=lambda finding: (order.get(finding.severity, 99), finding.check, finding.location))
    return findings
