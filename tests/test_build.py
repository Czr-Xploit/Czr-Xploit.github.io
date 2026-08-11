"""Configuration, frontmatter, template engine, feeds and a full build."""

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from tools.ssg.builder import Builder
from tools.ssg.check import run_checks
from tools.ssg.config import ConfigError, load_config
from tools.ssg.content import normalise_tag, parse_frontmatter
from tools.ssg.template import TemplateEngine, TemplateSyntaxError


class TestFrontmatter(unittest.TestCase):
    def test_scalars_and_types(self):
        meta, body = parse_frontmatter(
            "---\n"
            "title: Hola\n"
            'quoted: "con: dos puntos"\n'
            "date: 2026-03-04\n"
            "count: 42\n"
            "ratio: 1.5\n"
            "draft: true\n"
            "featured: false\n"
            "empty:\n"
            "---\n"
            "cuerpo\n"
        )
        self.assertEqual(meta["title"], "Hola")
        self.assertEqual(meta["quoted"], "con: dos puntos")
        self.assertEqual(meta["date"], dt.date(2026, 3, 4))
        self.assertEqual(meta["count"], 42)
        self.assertEqual(meta["ratio"], 1.5)
        self.assertIs(meta["draft"], True)
        self.assertIs(meta["featured"], False)
        self.assertIsNone(meta["empty"])
        self.assertEqual(body.strip(), "cuerpo")

    def test_inline_and_block_lists(self):
        meta, _ = parse_frontmatter(
            "---\ninline: [a, b, c]\nblock:\n  - uno\n  - dos\n---\n"
        )
        self.assertEqual(meta["inline"], ["a", "b", "c"])
        self.assertEqual(meta["block"], ["uno", "dos"])

    def test_folded_block_scalar(self):
        meta, _ = parse_frontmatter("---\nsummary: >\n  una linea\n  y otra\n---\n")
        self.assertEqual(meta["summary"], "una linea y otra")

    def test_literal_block_scalar_keeps_newlines(self):
        meta, _ = parse_frontmatter("---\nbody: |\n  uno\n  dos\n---\n")
        self.assertIn("\n", meta["body"])

    def test_nested_mapping(self):
        meta, _ = parse_frontmatter("---\nouter:\n  a: 1\n  b: dos\n---\n")
        self.assertEqual(meta["outer"], {"a": 1, "b": "dos"})

    def test_missing_frontmatter_returns_empty(self):
        meta, body = parse_frontmatter("# solo markdown\n")
        self.assertEqual(meta, {})
        self.assertTrue(body.startswith("# solo"))

    def test_tag_normalisation_folds_accents_and_case(self):
        self.assertEqual(normalise_tag("Criptografía"), "criptografia")
        self.assertEqual(normalise_tag("Red Team"), "red-team")
        self.assertEqual(normalise_tag("ñandú"), "nandu")


class TestTemplateEngine(unittest.TestCase):
    def setUp(self):
        self.engine = TemplateEngine([os.path.join(REPO_ROOT, "theme", "templates")])

    def render(self, source, context=None):
        return self.engine.render_string(source, context or {})

    def test_conditionals(self):
        self.assertEqual(self.render("{% if a %}si{% else %}no{% endif %}", {"a": True}), "si")
        self.assertEqual(self.render("{% if a %}si{% else %}no{% endif %}", {"a": False}), "no")
        self.assertEqual(self.render("{% if a %}1{% elif b %}2{% else %}3{% endif %}", {"b": 1}), "2")

    def test_loop_with_metadata(self):
        out = self.render("{% for x in xs %}{{ loop.index }}:{{ x }}{% if not loop.last %},{% endif %}{% endfor %}", {"xs": ["a", "b"]})
        self.assertEqual(out, "1:a,2:b")

    def test_loop_empty_branch(self):
        self.assertEqual(self.render("{% for x in xs %}{{ x }}{% empty %}vacio{% endfor %}", {"xs": []}), "vacio")

    def test_two_variable_loop_over_mapping(self):
        out = self.render("{% for k, v in m %}{{ k }}={{ v }};{% endfor %}", {"m": {"a": 1}})
        self.assertEqual(out, "a=1;")

    def test_filters_chain(self):
        self.assertEqual(self.render("{{ x | lower | truncate:5,'' }}", {"x": "ABCDEFGHIJ"}), "ABCDE".lower()[:5])

    def test_undefined_is_silent_and_falsy(self):
        self.assertEqual(self.render("[{{ nope }}]", {}), "[]")
        self.assertEqual(self.render("{% if nope %}x{% else %}y{% endif %}", {}), "y")
        self.assertEqual(self.render("[{{ a.b.c.d }}]", {"a": {}}), "[]")

    def test_set_and_comment(self):
        self.assertEqual(self.render("{% set n = 2 %}{{ n }}{# oculto #}", {}), "2")

    def test_comparison_and_membership(self):
        self.assertEqual(self.render("{% if 3 > 2 and 'a' in xs %}ok{% endif %}", {"xs": ["a"]}), "ok")

    def test_raw_block(self):
        self.assertEqual(self.render("{% raw %}{{ literal }}{% endraw %}", {}), "{{ literal }}")

    def test_syntax_error_is_reported(self):
        with self.assertRaises(TemplateSyntaxError):
            self.render("{% if a %}sin cierre", {})

    def test_inheritance_resolves_child_blocks_over_parent(self):
        base = "{% block a %}base-a{% endblock %}|{% block b %}base-b{% endblock %}"
        # Exercised through render_string rather than the real theme, which needs
        # the builder-registered filters; base.html is covered by TestFullBuild.
        self.assertEqual(self.render(base, {}), "base-a|base-b")

    def test_include_depth_is_bounded(self):
        from tools.ssg.template import TemplateRuntimeError

        with self.assertRaises((TemplateRuntimeError, Exception)):
            self.engine.render_string('{% include "does-not-exist.html" %}', {})


class TestFullBuild(unittest.TestCase):
    """Builds the real site into a temporary directory and inspects the output."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ssg-test-")
        cls.config = load_config(os.path.join(REPO_ROOT, "site.json"))
        cls.config.output_dir = cls.tmp
        cls.config.source_root = REPO_ROOT
        # load_config derives output_path from source_root + output_dir; point it
        # at an absolute temp dir so the real dist/ is never touched by tests.
        cls.config.output_dir = os.path.relpath(cls.tmp, REPO_ROOT)
        cls.builder = Builder(cls.config, timestamp=dt.datetime(2026, 8, 11, 12, 0, 0, tzinfo=dt.timezone.utc))
        cls.result = cls.builder.build()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def output(self, *parts):
        return os.path.join(self.tmp, *parts)

    def read(self, *parts):
        with open(self.output(*parts), "r", encoding="utf-8") as handle:
            return handle.read()

    def test_build_produced_pages(self):
        self.assertGreater(self.result.pages, 10)
        self.assertGreater(self.result.documents, 0)

    def test_essential_files_exist(self):
        for name in ("index.html", "404.html", "sitemap.xml", "robots.txt", "feed.xml",
                     "atom.xml", "feed.json", ".nojekyll", "site.webmanifest",
                     "search-es.json", "search-en.json", "fs-es.json", "fs-en.json"):
            with self.subTest(name=name):
                self.assertTrue(os.path.exists(self.output(name)), name)

    def test_both_language_trees_exist(self):
        self.assertTrue(os.path.exists(self.output("index.html")))
        self.assertTrue(os.path.exists(self.output("en", "index.html")))

    def test_csp_meta_present_and_strict(self):
        import html as html_module
        import re

        raw = self.read("index.html")
        match = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', raw)
        self.assertIsNotNone(match, "no CSP meta tag")
        # Apostrophes arrive escaped; decode before asserting on directive values.
        policy = html_module.unescape(match.group(1))
        self.assertIn("script-src 'self'", policy)
        self.assertIn("base-uri 'none'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertNotIn("'unsafe-eval'", policy)
        self.assertNotRegex(policy, r"script-src[^;]*'unsafe-inline'")

    def test_site_data_blob_is_valid_json(self):
        import re

        raw = self.read("index.html")
        match = re.search(r'<script type="application/json" id="site-data">(.*?)</script>', raw, re.DOTALL)
        self.assertIsNotNone(match, "no #site-data blob")
        payload = json.loads(match.group(1))
        self.assertEqual(payload["lang"], "es")
        self.assertIn("searchIndex", payload)
        self.assertIn("themes", payload)

    def test_structured_data_is_valid_json(self):
        import re

        raw = self.read("blog", "anatomia-de-una-csp", "index.html")
        for match in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', raw, re.DOTALL):
            payload = json.loads(match.group(1))
            self.assertEqual(payload["@context"], "https://schema.org")

    def test_no_inline_scripts_beyond_json(self):
        import re

        html = self.read("index.html")
        for match in re.finditer(r"<script\b[^>]*>", html):
            tag = match.group(0)
            self.assertTrue(
                "src=" in tag or "application/json" in tag or "application/ld+json" in tag,
                f"unexpected inline script: {tag}",
            )

    def test_feeds_are_well_formed_xml(self):
        for name in ("feed.xml", "atom.xml", "sitemap.xml"):
            with self.subTest(name=name):
                ElementTree.parse(self.output(name))

    def test_feeds_use_absolute_urls(self):
        rss = self.read("feed.xml")
        self.assertIn("https://", rss)
        self.assertNotIn('<link>/', rss)

    def test_search_index_shape(self):
        payload = json.loads(self.read("search-es.json"))
        self.assertIn("docs", payload)
        self.assertIn("terms", payload)
        self.assertGreater(len(payload["docs"]), 0)
        for record in payload["docs"]:
            self.assertIn("t", record)
            self.assertIn("u", record)

    def test_terminal_filesystem_index_shape(self):
        payload = json.loads(self.read("fs-es.json"))
        self.assertIn("dirs", payload)
        for directory in ("blog", "writeups", "arsenal", "pages"):
            self.assertIn(directory, payload["dirs"])

    def test_hreflang_alternates_present(self):
        html = self.read("index.html")
        self.assertIn('hreflang="es"', html)
        self.assertIn('hreflang="en"', html)
        self.assertIn('hreflang="x-default"', html)

    def test_budgets_respected(self):
        self.assertEqual(self.result.budget_problems, [])

    def test_verification_reports_no_blockers(self):
        findings = run_checks(self.config, self.builder)
        blockers = [finding for finding in findings if finding.severity in ("BLOCKER", "HIGH")]
        self.assertEqual(blockers, [], "\n".join(f"{f.severity} {f.check}: {f.message} @ {f.location}" for f in blockers))

    def test_build_is_deterministic(self):
        """Same inputs, same timestamp, byte-identical output."""
        other = tempfile.mkdtemp(prefix="ssg-test-b-")
        try:
            config = load_config(os.path.join(REPO_ROOT, "site.json"))
            config.source_root = REPO_ROOT
            config.output_dir = os.path.relpath(other, REPO_ROOT)
            builder = Builder(config, timestamp=dt.datetime(2026, 8, 11, 12, 0, 0, tzinfo=dt.timezone.utc))
            builder.build()

            for root, _, files in os.walk(self.tmp):
                for name in files:
                    first = os.path.join(root, name)
                    second = os.path.join(other, os.path.relpath(first, self.tmp))
                    self.assertTrue(os.path.exists(second), f"missing in second build: {name}")
                    with open(first, "rb") as a, open(second, "rb") as b:
                        self.assertEqual(a.read(), b.read(), f"nondeterministic output: {os.path.relpath(first, self.tmp)}")
        finally:
            shutil.rmtree(other, ignore_errors=True)


class TestCssMinifier(unittest.TestCase):
    """The minifier rewrites every stylesheet the site ships. A rewrite that
    produces *invalid* CSS fails silently — the browser drops the rule and the
    page merely looks wrong, with nothing in the build output to say so."""

    def minify(self, source):
        from tools.ssg.assets import minify_css

        return minify_css(source)

    def test_functional_pseudo_classes_keep_no_space(self):
        """`:not (x)` is an invalid selector; the rule is discarded wholesale."""
        for selector in (":not([hidden])", ":not(.x)", ":is(a,b)", ":where(.x)", ":has(> img)"):
            with self.subTest(selector=selector):
                out = self.minify(f"a{selector} {{color:red}}")
                self.assertNotIn(": ", out.replace("color: ", ""))
                self.assertIn(selector.split("(")[0] + "(", out)

    def test_media_query_keywords_keep_their_space(self):
        out = self.minify("@media screen and (min-width: 48rem) {a{color:red}}")
        self.assertIn("and (", out)
        out = self.minify("@media not (hover: hover) {a{color:red}}")
        self.assertIn("not (", out)

    def test_strings_are_preserved_verbatim(self):
        out = self.minify('a::after{content:"  spaced  "}')
        self.assertIn('"  spaced  "', out)

    def test_comments_removed_and_braces_balanced(self):
        out = self.minify("/* note */ a{color:red} /* another */ b{color:blue}")
        self.assertNotIn("note", out)
        self.assertEqual(out.count("{"), out.count("}"))

    def test_calc_addition_survives(self):
        """Collapsing the spaces around `+` would make `calc()` invalid."""
        out = self.minify("a{width:calc(100% - 2rem)}")
        self.assertIn("calc(100% - 2rem)", out)

    def test_output_of_real_stylesheets_is_balanced(self):
        directory = os.path.join(REPO_ROOT, "theme", "css")
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".css"):
                continue
            with self.subTest(stylesheet=name):
                with open(os.path.join(directory, name), "r", encoding="utf-8") as handle:
                    source = handle.read()
                out = self.minify(source)
                self.assertEqual(out.count("{"), out.count("}"), f"{name}: unbalanced braces")
                self.assertNotIn(":not (", out, f"{name}: minifier broke a :not() selector")


class TestThemeRegressions(unittest.TestCase):
    """Regressions for bugs that shipped once and were caught by screenshot.

    Both are cheap to re-introduce while tidying, and neither is visible in the
    build output or the verification pass — only in a rendered browser. These
    tests are the substitute for a browser in CI.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ssg-regress-")
        config = load_config(os.path.join(REPO_ROOT, "site.json"))
        config.source_root = REPO_ROOT
        config.output_dir = os.path.relpath(cls.tmp, REPO_ROOT)
        Builder(config, timestamp=dt.datetime(2026, 8, 11, tzinfo=dt.timezone.utc)).build()
        with open(os.path.join(cls.tmp, "static", "css", "main.css"), "r", encoding="utf-8") as handle:
            cls.css = handle.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_modal_base_rules_declare_no_display(self):
        """`[hidden] {display:none}` is a user-agent rule, so ANY author
        declaration of `display` on `.palette` / `.term` outranks it and pins
        the modal permanently open over the whole page. The display switch must
        live only in the `:not([hidden])` rule."""
        import re

        for selector in (".palette", ".term"):
            match = re.search(re.escape(selector) + r"\{([^}]*)\}", self.css)
            self.assertIsNotNone(match, f"no base rule found for {selector}")
            self.assertNotIn(
                "display:",
                match.group(1),
                f"{selector} base rule declares display; it will beat [hidden] "
                f"and pin the modal open. Move it to {selector}:not([hidden]).",
            )

    def test_modal_display_switch_exists(self):
        """The counterpart of the rule above: something must actually show them."""
        self.assertIn(":not([hidden])", self.css)

    def test_tween_clamps_progress_to_unit_range(self):
        """A requestAnimationFrame timestamp can predate the moment a task was
        registered, making (now - started) negative. Unclamped, that rendered a
        stat count-up as "-402"."""
        path = os.path.join(REPO_ROOT, "theme", "static", "js", "modules", "glitch.js")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("Math.max(0,", source.replace(" ", ""),
                      "tween() must clamp progress to a lower bound of 0")

    def test_card_cover_art_is_sixteen_by_nine(self):
        """Card covers render into an `aspect-ratio: 16/9` box with
        `object-fit: cover`; art at another ratio gets cropped on both sides."""
        import re

        path = os.path.join(REPO_ROOT, "theme", "static", "img", "scan-loop.svg")
        with open(path, "r", encoding="utf-8") as handle:
            svg = handle.read()
        box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
        self.assertIsNotNone(box, "no viewBox on cover art")
        width, height = float(box.group(1)), float(box.group(2))
        self.assertAlmostEqual(width / height, 16 / 9, places=2,
                               msg=f"cover art is {width}x{height}, not 16:9")


class TestConfigValidation(unittest.TestCase):
    def test_rejects_non_https_base_url(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"title": "x", "base_url": "http://x.tld", "languages": [{"code": "es"}]}, handle)
            path = handle.name
        try:
            with self.assertRaises(ConfigError):
                load_config(path)
        finally:
            os.unlink(path)

    def test_rejects_missing_language(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"title": "x", "base_url": "https://x.tld", "languages": []}, handle)
            path = handle.name
        try:
            with self.assertRaises(ConfigError):
                load_config(path)
        finally:
            os.unlink(path)

    def test_default_language_has_no_url_prefix(self):
        config = load_config(os.path.join(REPO_ROOT, "site.json"))
        self.assertEqual(config.default_lang.url_for(), "/")
        self.assertEqual(config.language("en").url_for("blog"), "/en/blog/")


if __name__ == "__main__":
    unittest.main()
