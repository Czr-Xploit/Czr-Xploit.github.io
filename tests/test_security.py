"""
Security regression tests.

Each case here is a payload that must not survive into the output. When adding a
feature that touches URL handling, attribute emission or raw HTML, add the
payload you were worried about to this file. A test that fails once and is then
fixed is worth more than a paragraph of documentation.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.ssg.markdown import render_markdown
from tools.ssg.sanitize import is_safe_url, sanitize_html
from tools.ssg.template import Markup, TemplateEngine, escape


class TestUrlScheme(unittest.TestCase):
    def test_rejects_script_schemes(self):
        for url in (
            "javascript:alert(1)",
            "JaVaScRiPt:alert(1)",
            "  javascript:alert(1)",
            "java\tscript:alert(1)",
            "java\x00script:alert(1)",
            "vbscript:msgbox",
            "data:text/html;base64,PHNjcmlwdD4=",
            "//evil.tld/x.js",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_safe_url(url), url)

    def test_accepts_ordinary_urls(self):
        for url in ("https://x.tld", "http://x.tld", "/blog/", "../a", "#frag", "mailto:a@b.tld"):
            with self.subTest(url=url):
                self.assertTrue(is_safe_url(url), url)

    def test_data_images_only_when_permitted(self):
        payload = "data:image/png;base64,iVBORw0KGgo="
        self.assertFalse(is_safe_url(payload))
        self.assertTrue(is_safe_url(payload, allow_data_images=True))


class TestSanitizer(unittest.TestCase):
    def assert_clean(self, fragment, *forbidden):
        out = sanitize_html(fragment)
        for token in forbidden:
            self.assertNotIn(token, out, f"{token!r} survived: {out!r}")
        return out

    def test_drops_script_and_its_content(self):
        out = self.assert_clean("<p>a</p><script>alert(1)</script><p>b</p>", "<script", "alert(1)")
        self.assertIn("<p>a</p>", out)
        self.assertIn("<p>b</p>", out)

    def test_drops_event_handlers(self):
        self.assert_clean('<img src="/a.png" onerror="alert(1)">', "onerror")

    def test_drops_style_attribute(self):
        self.assert_clean('<div style="position:fixed">x</div>', "style=")

    def test_drops_dangerous_elements(self):
        for fragment in (
            '<iframe src="//evil"></iframe>',
            '<object data="x"></object>',
            "<embed src=x>",
            '<form action="//evil"><input name=a></form>',
            "<style>body{display:none}</style>",
            '<base href="//evil">',
            '<meta http-equiv="refresh" content="0;url=//evil">',
        ):
            with self.subTest(fragment=fragment):
                out = sanitize_html(fragment)
                for token in ("<iframe", "<object", "<embed", "<form", "<style", "<base", "<meta"):
                    self.assertNotIn(token, out)

    def test_svg_event_handlers_removed_but_shape_kept(self):
        out = sanitize_html('<svg onload="alert(1)"><path d="M0 0"/></svg>')
        self.assertNotIn("onload", out)
        self.assertIn("<path", out)

    def test_srcset_rejected_when_any_candidate_is_unsafe(self):
        out = sanitize_html('<img src="/a.png" srcset="/a.png 1x, javascript:x 2x">')
        self.assertNotIn("srcset", out)
        self.assertIn('src="/a.png"', out)

    def test_target_blank_gets_noopener(self):
        out = sanitize_html('<a href="https://x.tld" target="_blank">x</a>')
        self.assertIn("noopener", out)
        self.assertIn("noreferrer", out)

    def test_unbalanced_markup_is_closed(self):
        out = sanitize_html("<div><span>a<b>b")
        self.assertEqual(out.count("<div"), out.count("</div"))
        self.assertEqual(out.count("<span"), out.count("</span"))

    def test_comments_are_dropped(self):
        self.assert_clean("<!-- --><p>a</p>", "<!--")


class TestMarkdownXss(unittest.TestCase):
    """The markdown layer builds some anchors and images itself, bypassing the
    sanitizer, so it needs its own coverage."""

    FORBIDDEN = ("javascript:", "vbscript:", "onerror", "onload", "<script", "<iframe", "data:text/html")

    def assert_clean(self, source):
        html = render_markdown(source).html
        for token in self.FORBIDDEN:
            # Escaped text is inert; only unescaped occurrences matter.
            self.assertNotIn(token, html.replace("&lt;", "<LT>"), f"{token!r} in {html!r}")

    def test_link_schemes(self):
        for source in (
            "[x](javascript:alert(1))",
            "[x](JAVASCRIPT:alert(1))",
            "[x][r]\n\n[r]: javascript:alert(1)",
            "<javascript:alert(1)>",
        ):
            with self.subTest(source=source):
                self.assert_clean(source)

    def test_image_schemes(self):
        for source in (
            "![x](javascript:alert(1))",
            "![x](data:text/html;base64,PHNjcmlwdD4=)",
            "![x](vbscript:msgbox)",
        ):
            with self.subTest(source=source):
                self.assert_clean(source)

    def test_gif_container_refuses_bad_source(self):
        html = render_markdown('::: gif src="javascript:alert(1)" poster="javascript:x"\ncap\n:::').html
        self.assertEqual(html.strip(), "")

    def test_refused_link_keeps_its_text(self):
        html = render_markdown("[texto visible](javascript:alert(1))").html
        self.assertIn("texto visible", html)
        self.assertNotIn("<a ", html)

    def test_raw_html_block_is_sanitized(self):
        self.assert_clean('<div onclick="alert(1)"><script>alert(2)</script></div>')

    def test_code_fence_cannot_break_out(self):
        """The highlighter wraps tokens in spans, so the escaped `</script>` is
        split across several of them. What matters is that no live tag survives,
        not that the escaped form appears contiguously."""
        html = render_markdown("```js\n</script><script>alert(1)</script>\n```").html
        self.assertNotIn("<script", html)
        self.assertNotIn("</script>", html)
        self.assertIn("&lt;", html)


class TestTemplateEscaping(unittest.TestCase):
    def setUp(self):
        self.engine = TemplateEngine([os.path.dirname(os.path.abspath(__file__))])

    def render(self, source, context):
        return self.engine.render_string(source, context)

    def test_interpolation_escapes_by_default(self):
        out = self.render("{{ x }}", {"x": '<img src=x onerror=alert(1)>'})
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)

    def test_attribute_context_escapes_quotes(self):
        out = self.render('<a title="{{ x }}">y</a>', {"x": '" onmouseover="alert(1)'})
        self.assertNotIn('onmouseover="', out)

    def test_markup_is_trusted(self):
        out = self.render("{{ x }}", {"x": Markup("<b>ok</b>")})
        self.assertEqual(out, "<b>ok</b>")

    def test_json_filter_cannot_close_a_script_element(self):
        out = self.render("{{ x | json }}", {"x": {"t": "</script><script>alert(1)</script>"}})
        self.assertNotIn("</script>", out)
        self.assertIn("\\u003c", out)

    def test_expressions_cannot_reach_the_interpreter(self):
        """Dunder access raises rather than resolving to undefined.

        Failing loudly is the right call here: a template reaching for
        ``__class__`` is either an attack or a bug, and in both cases the build
        should stop rather than quietly render an empty string.
        """
        from tools.ssg.template import TemplateRuntimeError

        for expression in (
            "{{ x.__class__ }}",
            "{{ x.__init__ }}",
            "{{ x.__class__.__mro__ }}",
            "{{ x.upper.__globals__ }}",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(TemplateRuntimeError):
                    self.render(expression, {"x": "abc"})

    def test_callables_are_not_auto_invoked(self):
        """Exposing data is fine; exposing behaviour is not."""

        class Probe:
            value = "data"

            def detonate(self):  # pragma: no cover - must never run
                raise AssertionError("template invoked a bound method")

        out = self.render("{{ p.value }}|{{ p.detonate }}", {"p": Probe()})
        self.assertEqual(out, "data|")

    def test_template_names_cannot_traverse(self):
        from tools.ssg.template import TemplateError

        with self.assertRaises(TemplateError):
            self.engine.load("../../../etc/passwd")

    def test_escape_handles_none_and_bools(self):
        self.assertEqual(escape(None), "")
        self.assertEqual(escape(True), "true")


if __name__ == "__main__":
    unittest.main()
