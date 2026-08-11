"""Markdown parser and inline renderer."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.ssg.markdown import Markdown, plain_text, render_markdown, slugify


class TestSlugify(unittest.TestCase):
    def test_folds_spanish_accents(self):
        self.assertEqual(slugify("Análisis de vulnerabilidades"), "analisis-de-vulnerabilidades")
        self.assertEqual(slugify("Año Ñandú"), "ano-nandu")

    def test_collapses_punctuation_and_runs(self):
        self.assertEqual(slugify("¿Qué   pasa --- aquí?"), "que-pasa-aqui")

    def test_never_returns_empty(self):
        self.assertEqual(slugify("!!!"), "section")
        self.assertEqual(slugify(""), "section")

    def test_respects_max_length_on_word_boundary(self):
        slug = slugify("a" * 20 + " " + "b" * 20 + " " + "c" * 60, max_length=30)
        self.assertLessEqual(len(slug), 30)
        self.assertFalse(slug.endswith("-"))


class TestInline(unittest.TestCase):
    def render(self, source):
        return render_markdown(source, lang="es").html

    def test_basic_emphasis(self):
        html = self.render("**a** *b* `c` ~~d~~ ==e==")
        self.assertIn("<strong>a</strong>", html)
        self.assertIn("<em>b</em>", html)
        self.assertIn("<code>c</code>", html)
        self.assertIn("<del>d</del>", html)
        self.assertIn("<mark>e</mark>", html)

    def test_keyboard_combo_splits_on_plus(self):
        html = self.render("++Ctrl+Shift+K++")
        self.assertIn("<kbd>Ctrl</kbd>", html)
        self.assertIn("<kbd>Shift</kbd>", html)
        self.assertIn("<kbd>K</kbd>", html)

    def test_code_span_content_is_not_parsed(self):
        html = self.render("`**not bold**`")
        self.assertIn("<code>**not bold**</code>", html)
        self.assertNotIn("<strong>", html)

    def test_external_links_get_safety_attributes(self):
        html = self.render("[x](https://example.tld)")
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('target="_blank"', html)

    def test_internal_links_stay_clean(self):
        html = self.render("[x](/blog/post/)")
        self.assertNotIn("target=", html)
        self.assertIn('href="/blog/post/"', html)

    def test_backslash_escape(self):
        html = self.render(r"\*no emphasis\*")
        self.assertNotIn("<em>", html)


class TestBlocks(unittest.TestCase):
    def render(self, source):
        return render_markdown(source, lang="es").html

    def test_heading_gets_stable_id_and_anchor(self):
        html = self.render("## Sección de prueba")
        self.assertIn('id="seccion-de-prueba"', html)
        self.assertIn('class="heading-anchor"', html)

    def test_duplicate_headings_get_distinct_ids(self):
        result = render_markdown("## Uno\n\n## Uno\n\n## Uno")
        slugs = [heading.slug for heading in result.headings]
        self.assertEqual(slugs, ["uno", "uno-2", "uno-3"])

    def test_table_with_alignment(self):
        html = self.render("| a | b |\n|:--|--:|\n| 1 | 2 |")
        self.assertIn('class="ta-left"', html)
        self.assertIn('class="ta-right"', html)
        self.assertIn("<tbody>", html)

    def test_task_list(self):
        html = self.render("- [x] hecho\n- [ ] pendiente")
        self.assertIn("task-item is-done", html)
        self.assertIn('class="task-item"', html)

    def test_nested_list(self):
        html = self.render("- a\n- b\n  - c")
        self.assertEqual(html.count("<ul"), 2)
        self.assertIn("c</li>", html)

    def test_fenced_code_is_highlighted_and_escaped(self):
        html = self.render("```python\ndef f():\n    return '<b>'\n```")
        self.assertIn("tok-kw", html)
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>", html)

    def test_code_fence_title_and_line_numbers(self):
        html = self.render('```python title="x.py" highlight="2"\na = 1\nb = 2\n```')
        self.assertIn("x.py", html)
        self.assertIn("with-numbers", html)
        self.assertIn("ln-hl", html)

    def test_footnotes_render_and_backlink(self):
        html = self.render("Texto.[^a]\n\n[^a]: La nota.")
        self.assertIn('class="footnote-ref"', html)
        self.assertIn('id="fn-a"', html)
        self.assertIn('class="footnote-back"', html)

    def test_horizontal_rule(self):
        self.assertIn('<hr class="rule" />', self.render("---"))

    def test_blockquote_and_github_alert(self):
        self.assertIn("<blockquote>", self.render("> cita"))
        self.assertIn("callout-warning", self.render("> [!WARNING]\n> ojo"))


class TestContainers(unittest.TestCase):
    def render(self, source):
        return render_markdown(source, lang="es").html

    def test_callout_variants(self):
        for name in ("note", "tip", "warning", "danger", "success"):
            html = self.render(f"::: {name}\ncuerpo\n:::")
            self.assertIn(f"callout-{name}", html)

    def test_callout_custom_title(self):
        html = self.render('::: warning title="Ojo"\nx\n:::')
        self.assertIn("Ojo", html)

    def test_terminal_container(self):
        html = self.render("::: terminal title=\"czr@lab\"\nczr@lab:~$ id\nuid=0\n:::")
        self.assertIn("terminal-block", html)
        self.assertIn("tok-pmt", html)

    def test_spoiler_container(self):
        html = self.render('::: spoiler title="Ver"\noculto\n:::')
        self.assertIn("<details", html)
        self.assertIn("<summary>", html)

    def test_timeline_container(self):
        html = self.render("::: timeline\n- Día 0 — contacto\n- Día 90 — publicación\n:::")
        self.assertIn('class="timeline"', html)
        self.assertIn("timeline-date", html)

    def test_gif_container_builds_click_to_play(self):
        html = self.render('::: gif src="/static/media/gif/a.gif" poster="/static/img/a.png" alt="x"\npie\n:::')
        self.assertIn("gif-figure", html)
        self.assertIn('data-gif="/static/media/gif/a.gif"', html)
        self.assertIn('data-action="toggle-gif"', html)
        self.assertIn("<noscript>", html)

    def test_nested_containers(self):
        html = self.render("::: note\n::: warning\ndentro\n:::\nfuera\n:::")
        self.assertIn("callout-note", html)
        self.assertIn("callout-warning", html)


class TestMetadata(unittest.TestCase):
    def test_collects_links_media_and_languages(self):
        result = render_markdown(
            "[a](https://x.tld)\n\n![i](/static/img/i.png)\n\n```rust\nfn main() {}\n```"
        )
        self.assertIn("https://x.tld", result.links)
        self.assertIn("/static/img/i.png", result.media)
        self.assertIn("rust", result.code_languages)

    def test_word_count_and_excerpt(self):
        result = render_markdown("# T\n\n" + "palabra " * 80)
        self.assertGreater(result.word_count, 70)
        self.assertTrue(result.excerpt)
        self.assertLessEqual(len(result.excerpt), 241)

    def test_toc_only_includes_h2_to_h4(self):
        result = render_markdown("# h1\n\n## h2\n\n### h3\n\n##### h5")
        levels = {entry["level"] for entry in result.toc}
        self.assertTrue(levels.issubset({2, 3, 4}))

    def test_plain_text_strips_markup(self):
        self.assertEqual(plain_text("<p>a <b>b</b></p>"), "a b")


if __name__ == "__main__":
    unittest.main()
