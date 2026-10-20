"""
Offline static checks for issue #65: one chalkboard-and-paper look for
docs/visual/index.html (no per-subject themes, palette in :root, contrast,
drawn icons, readable sizes). No browser, no network, no LLM calls.
"""

from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "docs" / "visual" / "index.html"
HTML = PAGE.read_text(encoding="utf-8")

CSS = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", HTML, re.S))
CSS_NC = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
SCRIPT = "\n".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", HTML, re.S))
MARKUP = re.sub(r"<(script|style)\b.*?</\1>", "", HTML, flags=re.S | re.I)

EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF☀-⛿⭐⭕✅✨❌❓➕-➗️]"
)


# ---------- helpers ----------
def _rules():
    """(selector, {prop: value}) for every simple rule, media blocks flattened."""
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS_NC):
        decls = {}
        for d in body.split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip().lower()] = v.strip()
        for s in sel.split(","):
            out.append((" ".join(s.split()), decls))
    return out


def _root_vars():
    m = re.search(r":root\s*\{([^}]*)\}", CSS_NC)
    assert m, "no :root block"
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1))}


def _find_var(*patterns, exclude=()):
    for name, val in _root_vars().items():
        n = name.lower()
        if any(re.search(p, n) for p in patterns) and not any(re.search(e, n) for e in exclude):
            if re.fullmatch(r"#[0-9a-fA-F]{3,6}", val):
                return name, val
    raise AssertionError(f":root has no colour variable matching {patterns}")


def _hex(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _lum(h):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (f(c) for c in _hex(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _resolve(val):
    """Resolve a background/color value to a hex colour (follows var(--x))."""
    m = re.search(r"var\((--[\w-]+)", val)
    if m:
        return _resolve(_root_vars().get(m.group(1), ""))
    m = re.search(r"#[0-9a-fA-F]{3,6}\b", val)
    return m.group(0) if m else None


def _prop(selector, prop):
    """Last declared value of prop for exact selector."""
    val = None
    for sel, d in _rules():
        if sel == selector and prop in d:
            val = d[prop]
    return val


def _bg(selector):
    v = _prop(selector, "background") or _prop(selector, "background-color")
    assert v, f"{selector} has no background"
    return v


PAPER = lambda: _find_var(r"paper", r"^--bg", r"page", exclude=(r"board", r"card"))  # noqa: E731
INK = lambda: _find_var(r"ink", r"^--text", r"^--fg", exclude=(r"muted", r"board", r"on-"))  # noqa: E731
MUTED = lambda: _find_var(r"muted", r"dim", r"subtle")  # noqa: E731
BORDER = lambda: _find_var(r"border", r"line", r"rule")  # noqa: E731
BOARD = lambda: _find_var(r"board", r"chalkboard", r"green", exclude=(r"ink", r"text", r"on-"))  # noqa: E731
CHALK = lambda: _find_var(r"chalk", r"yellow", exclude=(r"board",))  # noqa: E731


# ---------- one look ----------
def test_no_per_subject_themes():
    assert "data-theme" not in HTML
    for token in ("TOPIC_THEME", "THEME_WHY", "applyTheme"):
        assert token not in HTML, token


def test_theme_note_is_gone():
    assert "theme-note" not in HTML or "Theme:" not in HTML
    assert not re.search(r"Theme:\s", HTML)


# ---------- colours in one place ----------
def test_root_palette_names_required_colours():
    for fn in (PAPER, INK, MUTED, BORDER, BOARD, CHALK):
        fn()


def test_root_block_is_single_and_near_top_of_stylesheet():
    assert len(re.findall(r":root\s*\{", CSS_NC)) == 1
    assert CSS_NC.index(":root") < 400


def test_purple_palette_is_gone():
    for c in ("#6366f1", "#4f46e5", "#8b5cf6", "#7c3aed", "#eef2ff", "#e0e7ff", "#c7d2fe"):
        assert c not in HTML.lower(), c


def test_no_saturated_purple_hue_in_any_hex_colour():
    import colorsys

    bad = []
    for h in set(re.findall(r"#([0-9a-fA-F]{6})\b", HTML)):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        hue, light, sat = colorsys.rgb_to_hls(r, g, b)
        if 255 <= hue * 360 <= 300 and sat > 0.25:
            bad.append(f"#{h} hue={hue * 360:.0f} sat={sat:.2f}")
    assert not bad, bad


# ---------- board + paper ----------
def _uses_var(value, var_name):
    return f"var({var_name})" in value


def test_header_and_brain_use_chalkboard_green():
    board, _ = BOARD()
    for sel in ("header", ".brain"):
        assert _uses_var(_bg(sel), board) or _resolve(_bg(sel)) == BOARD()[1], sel


def test_page_and_lesson_use_light_paper():
    for sel in ("body", ".lesson"):
        h = _resolve(_bg(sel))
        assert h, f"{sel} background not a plain colour/var"
        assert _lum(h) > 0.7, f"{sel} background not light: {h}"


# ---------- reading is dark on light ----------
def test_lesson_text_is_dark_on_light_at_7_to_1():
    for sel in (".lesson", ".body"):
        fg = _prop(sel, "color") or _prop(".lesson", "color") or _prop("body", "color")
        fg = _resolve(fg)
        bg = _resolve(_bg(".lesson"))
        assert _lum(bg) > _lum(fg), sel
        assert _ratio(fg, bg) >= 7, (sel, _ratio(fg, bg))


# ---------- yellow only highlights ----------
def test_chalk_yellow_never_a_large_background_or_body_text():
    name, _ = CHALK()
    banned = ("body", ".lesson", ".setup", ".brain", "header", ".wrap", "main", "html")
    for sel, d in _rules():
        if sel in banned:
            for prop in ("background", "background-color", "color"):
                assert name not in d.get(prop, ""), f"{sel} {prop} uses {name}"
    for sel in (".body", ".lesson p", ".body p"):
        assert name not in (_prop(sel, "color") or "")


# ---------- readable contrast ----------
def test_palette_text_contrast_at_least_4_5():
    paper, ink, muted = PAPER()[1], INK()[1], MUTED()[1]
    assert _ratio(ink, paper) >= 4.5
    assert _ratio(muted, paper) >= 4.5
    card = _resolve(_bg(".lesson"))
    assert _ratio(ink, card) >= 4.5
    assert _ratio(muted, card) >= 4.5


def test_text_on_chalkboard_green_contrast_at_least_4_5():
    board = BOARD()[1]
    vals = [v for n, v in _root_vars().items() if re.search(r"on-board|board-ink|board-text|chalk-text|on-green", n)]
    assert vals, ":root needs a text colour for use on the chalkboard (e.g. --on-board)"
    for v in vals:
        assert _ratio(_resolve(v), board) >= 4.5


# ---------- fonts ----------
def test_no_google_fonts_hosts_anywhere_in_page():
    assert "fonts.googleapis.com" not in HTML
    assert "fonts.gstatic.com" not in HTML


FONT_DIR = PAGE.parent / "fonts"


def test_woff2_files_ship_in_fonts_folder_with_ofl_licence():
    assert list(FONT_DIR.glob("*.woff2")), "no .woff2 files in docs/visual/fonts/"
    names = [p.name.upper() for p in FONT_DIR.iterdir()]
    assert any("OFL" in n or "LICENSE" in n or "LICENCE" in n for n in names)
    lic = next(p for p in FONT_DIR.iterdir()
               if any(k in p.name.upper() for k in ("OFL", "LICENSE", "LICENCE")))
    assert "SIL OPEN FONT LICENSE" in lic.read_text(encoding="utf-8", errors="ignore").upper()


def test_font_face_rules_use_relative_urls_swap_and_existing_files():
    faces = re.findall(r"@font-face\s*\{([^{}]*)\}", CSS_NC)
    assert faces, "no @font-face rules"
    for body in faces:
        assert re.search(r"font-display\s*:\s*swap", body), body
        urls = re.findall(r"url\(\s*['\"]?([^'\")]+)", body)
        assert urls, body
        for u in urls:
            assert not re.match(r"(https?:)?//|/", u), f"not relative: {u}"
            assert u.split("?")[0].endswith(".woff2"), u
            assert (PAGE.parent / u).is_file(), f"missing font file {u}"


def test_web_font_families_have_generic_fallback():
    fams = re.findall(r"font-family\s*:\s*([^;}]+)", CSS_NC)
    assert fams
    for f in fams:
        if "var(" in f or "inherit" in f:
            continue
        assert re.search(r"\b(sans-serif|serif|monospace)\b", f), f
    for name, val in _root_vars().items():
        if "font" in name:
            assert re.search(r"\b(sans-serif|serif|monospace)\b", val), name


# ---------- icons ----------
def test_logo_uses_aria_hidden_svg_not_emoji():
    m = re.search(r'<div class="logo"[^>]*>(.*?)</div>', MARKUP, re.S)
    assert m
    assert "<svg" in m.group(1) and 'aria-hidden="true"' in m.group(1)
    assert not EMOJI.search(m.group(1))


def test_no_emoji_in_static_markup():
    hits = EMOJI.findall(MARKUP)
    assert not hits, hits


def test_subject_chips_have_no_emoji():
    m = re.search(r"DOMAINS\s*=\s*\[(.*?)\];", SCRIPT, re.S)
    assert m, "subject list not found"
    assert 'label:' in m.group(1)
    assert not EMOJI.search(m.group(1))


def test_flowchart_node_labels_have_no_emoji():
    nodes = re.findall(r'<g class="fnode".*?</g>', MARKUP, re.S)
    assert len(nodes) >= 6
    for n in nodes:
        assert not EMOJI.search(n), n


# ---------- sizes ----------
def test_no_font_size_below_12px():
    sizes = re.findall(r"font-size\s*:\s*([\d.]+)(px|rem|em)", CSS_NC)
    assert sizes
    for val, unit in sizes:
        px = float(val) * (1 if unit == "px" else 16)
        assert px >= 12, f"{val}{unit}"


# ---------- format colours ----------
def test_format_pills_keep_distinct_colours_from_root_vars():
    seen = set()
    for kind in ("reading", "socratic", "interactive"):
        bg, fg = _prop(f".pill.{kind}", "background"), _prop(f".pill.{kind}", "color")
        assert bg and fg, kind
        assert "var(" in bg and "var(" in fg, f"{kind} pill must use :root variables"
        seen.add((bg, fg))
    assert len(seen) == 3


# ---------- failure cases ----------
def test_eval_tab_has_no_separate_colour_scheme():
    # no tab-scoped or body-state overrides of the palette
    assert not re.search(r"body\[[^\]]+\]|body\.\w+\s*\{[^}]*--", CSS_NC)
    assert not re.search(r"(#tab-eval|\.tab-eval|#eval-view|\[data-tab)[^{]*\{[^}]*--[\w-]+\s*:", CSS_NC)


def test_only_one_root_palette_no_redefinition_elsewhere():
    outside = re.sub(r":root\s*\{[^}]*\}", "", CSS_NC)
    assert not re.search(r"(^|[;{\s])--(bg|ink|paper|board|chalk|muted)[\w-]*\s*:", outside)
