"""
UI string table.

Every user-visible string that lives in a template rather than in an article
belongs here, keyed once and translated per language.  Templates read them as
``{{ t.some_key }}``, which means a missing translation shows up as an empty
string in review rather than as an English word leaking into the Spanish site.
"""

from __future__ import annotations

from typing import Any

__all__ = ["STRINGS", "strings_for", "MONTHS", "format_date"]


STRINGS: dict[str, dict[str, str]] = {
    # -- navigation ------------------------------------------------------- #
    "nav_home": {"es": "inicio", "en": "home"},
    "nav_research": {"es": "research", "en": "research"},
    "nav_writeups": {"es": "writeups", "en": "writeups"},
    "nav_arsenal": {"es": "arsenal", "en": "arsenal"},
    "nav_whoami": {"es": "whoami", "en": "whoami"},
    "nav_tags": {"es": "tags", "en": "tags"},
    "nav_search": {"es": "buscar", "en": "search"},
    "skip_to_content": {"es": "Saltar al contenido", "en": "Skip to content"},
    "main_nav": {"es": "Navegación principal", "en": "Main navigation"},

    # -- home ------------------------------------------------------------- #
    "hero_role": {"es": "investigación ofensiva y análisis de vulnerabilidades", "en": "offensive research and vulnerability analysis"},
    "latest": {"es": "Últimas publicaciones", "en": "Latest publications"},
    "featured": {"es": "Destacado", "en": "Featured"},
    "all_posts": {"es": "Ver todo el research", "en": "Browse all research"},
    "all_writeups": {"es": "Ver todos los writeups", "en": "Browse all writeups"},
    "stats_posts": {"es": "artículos", "en": "articles"},
    "stats_writeups": {"es": "writeups", "en": "writeups"},
    "stats_tools": {"es": "herramientas", "en": "tools"},
    "stats_words": {"es": "palabras", "en": "words"},

    # -- listings --------------------------------------------------------- #
    "research_title": {"es": "Research", "en": "Research"},
    "research_intro": {
        "es": "Investigación propia: análisis de vulnerabilidades, ingeniería inversa y notas de laboratorio.",
        "en": "Original research: vulnerability analysis, reverse engineering and lab notes.",
    },
    "writeups_title": {"es": "Writeups", "en": "Writeups"},
    "writeups_intro": {
        "es": "Resoluciones de laboratorios y retos. El razonamiento importa más que el comando ganador.",
        "en": "Lab and challenge walkthroughs. The reasoning matters more than the winning command.",
    },
    "arsenal_title": {"es": "Arsenal", "en": "Arsenal"},
    "arsenal_intro": {
        "es": "Herramientas y recursos que uso de verdad, con la nota de por qué.",
        "en": "Tools and resources I actually use, with a note on why.",
    },
    "tags_title": {"es": "Etiquetas", "en": "Tags"},
    "tag_prefix": {"es": "Etiqueta", "en": "Tag"},
    "empty_list": {"es": "Todavía no hay nada publicado aquí.", "en": "Nothing published here yet."},
    "no_results": {"es": "Sin resultados.", "en": "No results."},

    # -- article furniture ------------------------------------------------ #
    "published": {"es": "Publicado", "en": "Published"},
    "updated": {"es": "Actualizado", "en": "Updated"},
    "reading_time": {"es": "min de lectura", "en": "min read"},
    "toc_title": {"es": "Contenido", "en": "Contents"},
    "share": {"es": "Compartir", "en": "Share"},
    "copy_link": {"es": "Copiar enlace", "en": "Copy link"},
    "link_copied": {"es": "Enlace copiado", "en": "Link copied"},
    "previous_post": {"es": "Anterior", "en": "Previous"},
    "next_post": {"es": "Siguiente", "en": "Next"},
    "related": {"es": "Relacionado", "en": "Related"},
    "back_to_top": {"es": "Volver arriba", "en": "Back to top"},
    "read_more": {"es": "Leer", "en": "Read"},
    "on_this_page": {"es": "En esta página", "en": "On this page"},

    # -- writeup metadata ------------------------------------------------- #
    "platform": {"es": "Plataforma", "en": "Platform"},
    "difficulty": {"es": "Dificultad", "en": "Difficulty"},
    "operating_system": {"es": "Sistema", "en": "System"},
    "techniques": {"es": "Técnicas", "en": "Techniques"},
    "severity": {"es": "Severidad", "en": "Severity"},
    "disclosure": {"es": "Divulgación", "en": "Disclosure"},

    # -- search / palette / terminal -------------------------------------- #
    "search_title": {"es": "Buscar", "en": "Search"},
    "search_placeholder": {"es": "Buscar en el sitio…", "en": "Search the site…"},
    "search_hint": {"es": "Escribe para buscar. Esc para cerrar.", "en": "Type to search. Esc to close."},
    "search_results_count": {"es": "resultados", "en": "results"},
    "palette_open": {"es": "Abrir buscador", "en": "Open search"},
    "palette_title": {"es": "Paleta de comandos", "en": "Command palette"},
    "terminal_title": {"es": "Terminal", "en": "Terminal"},
    "terminal_hint": {"es": "Escribe 'help' para ver los comandos.", "en": "Type 'help' to list commands."},
    "terminal_open": {"es": "Abrir terminal", "en": "Open terminal"},
    "terminal_close": {"es": "Cerrar terminal", "en": "Close terminal"},

    # -- controls --------------------------------------------------------- #
    "theme_switch": {"es": "Cambiar tema", "en": "Switch theme"},
    "theme_phosphor": {"es": "fósforo", "en": "phosphor"},
    "theme_amber": {"es": "ámbar", "en": "amber"},
    "theme_ice": {"es": "hielo", "en": "ice"},
    "theme_redteam": {"es": "red team", "en": "red team"},
    "motion_toggle": {"es": "Efectos visuales", "en": "Visual effects"},
    "lang_switch": {"es": "Cambiar idioma", "en": "Switch language"},
    "menu_open": {"es": "Abrir menú", "en": "Open menu"},
    "menu_close": {"es": "Cerrar menú", "en": "Close menu"},

    # -- footer ----------------------------------------------------------- #
    "footer_built": {"es": "Generado estáticamente. Cero dependencias, cero rastreadores.", "en": "Statically generated. Zero dependencies, zero trackers."},
    "footer_source": {"es": "Código fuente", "en": "Source code"},
    "footer_feed": {"es": "Feed RSS", "en": "RSS feed"},
    "footer_pgp": {"es": "Clave PGP", "en": "PGP key"},
    "footer_license": {"es": "Contenido bajo CC BY-NC-SA 4.0. Código bajo MIT.", "en": "Content under CC BY-NC-SA 4.0. Code under MIT."},

    # -- errors ----------------------------------------------------------- #
    "notfound_title": {"es": "404 — Ruta no encontrada", "en": "404 — Route not found"},
    "notfound_body": {
        "es": "El recurso solicitado no existe en este host. Comprueba la URL o vuelve al índice.",
        "en": "The requested resource does not exist on this host. Check the URL or return to the index.",
    },
    "notfound_home": {"es": "Volver al inicio", "en": "Return home"},

    # -- pagination ------------------------------------------------------- #
    "page_previous": {"es": "Página anterior", "en": "Previous page"},
    "page_next": {"es": "Página siguiente", "en": "Next page"},
    "page_of": {"es": "de", "en": "of"},
    "page": {"es": "Página", "en": "Page"},

    # -- misc ------------------------------------------------------------- #
    "draft_badge": {"es": "borrador", "en": "draft"},
    "external_link": {"es": "enlace externo", "en": "external link"},
    "loading": {"es": "Cargando…", "en": "Loading…"},
    "js_required": {
        "es": "Esta función necesita JavaScript. El resto del sitio funciona sin él.",
        "en": "This feature needs JavaScript. The rest of the site works without it.",
    },
}


MONTHS: dict[str, list[str]] = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def strings_for(lang: str) -> dict[str, str]:
    """Flatten the table for one language, falling back to Spanish."""
    return {key: value.get(lang, value.get("es", "")) for key, value in STRINGS.items()}


def format_date(value: Any, lang: str) -> str:
    """Locale-ish date formatting without touching the C locale.

    ``locale.setlocale`` is process-global and depends on which locales the
    build machine happens to have generated -- a classic source of builds that
    differ between a laptop and CI.  A twelve-element list is not elegant, but
    it is deterministic everywhere.
    """
    if value is None:
        return ""
    if not hasattr(value, "month"):
        return str(value)
    months = MONTHS.get(lang, MONTHS["es"])
    month = months[value.month - 1]
    if lang == "es":
        return f"{value.day} {month} {value.year}"
    return f"{month} {value.day}, {value.year}"
