"""
Offline static checks for issue #75: a 3-step "what happens after Start" strip
under the Start button on the home board. Reads docs/visual/index.html only.
No browser, no network, no LLM calls.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_visual_accessibility import HTML
from test_visual_home import (
    _by_id, _fn_body, _order, _phone_css, _rules, _start, _text,
)
from test_visual_theme import _ratio, _resolve

DECISIONS = Path(__file__).resolve().parent.parent / "docs" / "DESIGN_DECISIONS.md"
LABELS = ["pick a subject", "find your gap", "adjust"]


def _hero():
    hero = next((a for a in _start().ancestors() if a.tag == "section"), None)
    assert hero is not None, "#start must sit inside the hero <section>"
    return hero


def _strip():
    lists = [e for e in _hero().descendants() if e.tag == "ol"]
    assert len(lists) == 1, "expected exactly one <ol> in the home hero"
    return lists[0]


def _steps():
    return [c for c in _strip().children if c.tag == "li"]


def _names(el):
    out = []
    for e in [el, *el.ancestors()]:
        n = []
        if e.attrs.get("id"):
            n.append(f"#{e.attrs['id']}")
        n += [f".{c}" for c in e.attrs.get("class", "").split()]
        out += n + [e.tag + x for x in n] + [e.tag]
    return out


def _strip_rules():
    """Rules whose selector targets the strip (its ol, li, or their class/id)."""
    strip = _strip()
    ids = {f"#{strip.attrs['id']}"} if strip.attrs.get("id") else set()
    cls = {f".{c}" for c in strip.attrs.get("class", "").split()}
    for li in _steps():
        cls |= {f".{c}" for c in li.attrs.get("class", "").split()}
    keys = ids | cls
    out = []
    for sel, props in _rules():
        toks = re.findall(r"[#.][\w-]+", sel)
        if any(t in keys for t in toks):
            out.append((sel, props))
    return out


def _effective(el, prop):
    """Nearest declared value of prop on el or an ancestor (by id/class/tag selector)."""
    for e in [el, *el.ancestors()]:
        names = _names(e)[: 1 + 2 * (len(e.attrs.get("class", "").split()) + bool(e.attrs.get("id")))]
        val = None
        for sel, props in _rules():
            last = sel.split()[-1] if sel.split() else sel
            if (last in names or sel in names) and prop in props:
                val = props[prop]
        if val:
            return val
    return None


# ---------- list of exactly three steps, in order, after the hint ----------
def test_home_has_ordered_list_of_exactly_three_steps_in_order():
    steps = _steps()
    assert len(steps) == 3
    texts = [_text(s).lower() for s in steps]
    for text, want in zip(texts, LABELS):
        assert want in text, (text, want)
    assert all(len(_text(s).split()) <= 5 for s in steps), "labels must be at most five words"


def test_strip_sits_after_no_account_needed_inside_the_hero():
    hint = [e for e in _hero().descendants() if not e.children and _text(e).lower() == "no account needed."]
    assert len(hint) == 1
    assert _order(_strip()) > _order(hint[0])
    assert _order(_strip()) > _order(_start())


# ---------- icons decorative ----------
def test_each_step_has_visible_text_and_decorative_icon():
    for s in _steps():
        assert _text(s), "step has no visible text"
        icons = [d for d in s.descendants() if d.tag in ("svg", "img", "i") or "icon" in d.attrs.get("class", "")]
        assert icons, "step has no icon"
        for ic in icons:
            assert ic.attrs.get("aria-hidden") == "true", "icon must be aria-hidden"
            assert not ic.attrs.get("aria-label")
            assert ic.attrs.get("role") != "img"
        for d in s.descendants():
            if d.tag == "svg":
                assert not [t for t in d.descendants() if t.tag == "title"]


# ---------- no buttons or links ----------
def test_strip_has_no_buttons_or_links():
    for d in [_strip(), *_strip().descendants()]:
        assert d.tag not in ("a", "button", "input", "select", "textarea")
        assert "onclick" not in d.attrs and "tabindex" not in d.attrs
        assert d.attrs.get("role") not in ("button", "link")


# ---------- #start does not move ----------
def test_strip_is_below_start_and_does_not_shift_it():
    strip = _strip()
    assert strip not in list(_start().ancestors())
    assert _start() not in list(strip.ancestors())
    for sel, props in _strip_rules():
        assert props.get("position") not in ("absolute", "fixed"), sel
        assert not props.get("order"), sel
    for a in strip.ancestors():
        if a.tag == "div" and "row" in a.attrs.get("class", "").split():
            raise AssertionError("strip must not live in the button row")


# ---------- phone ----------
def test_strip_stacks_or_wraps_at_390px_without_clipping():
    rules = _strip_rules()
    assert rules, "no CSS targets the strip"
    for sel, props in rules:
        for k in ("width", "min-width"):
            m = re.match(r"(\d+(?:\.\d+)?)px", props.get(k, ""))
            assert not m or float(m.group(1)) <= 340, (sel, k)
    base = {}
    for _, p in rules:
        base.update(p)
    phone = {}
    strip_toks = {t for s, _ in rules for t in re.findall(r"[#.][\w-]+", s)}
    for sel, props in _rules(_phone_css()):
        if any(t in strip_toks for t in re.findall(r"[#.][\w-]+", sel)):
            phone.update(props)
    merged = {**base, **phone}
    stacks = (
        "column" in merged.get("flex-direction", "")
        or merged.get("flex-wrap", "") == "wrap"
        or merged.get("display", "") == "block"
        or re.match(r"(1fr|minmax\(0,\s*1fr\)|repeat\(\s*1\b)", merged.get("grid-template-columns", ""))
        or "auto-fit" in merged.get("grid-template-columns", "")
        or "auto-fill" in merged.get("grid-template-columns", "")
    )
    assert stacks, "strip neither stacks nor wraps on phone"
    assert "nowrap" not in merged.get("white-space", "")


# ---------- contrast ----------
def test_strip_text_contrast_at_least_4_5():
    bg_val = _effective(_strip(), "background") or _effective(_strip(), "background-color")
    bg = _resolve(bg_val) if bg_val else None
    if bg is None:  # transparent: falls back to the hero board
        bg_val = _effective(_hero(), "background") or _effective(_hero(), "background-color")
        bg = _resolve(bg_val or "")
    assert bg, "cannot resolve the strip's background colour"
    for s in _steps():
        fg_val = _effective(s, "color")
        fg = _resolve(fg_val or "")
        assert fg, "cannot resolve the strip's text colour"
        assert _ratio(fg, bg) >= 4.5, (fg, bg)


# ---------- failure case: session start / change topic ----------
def test_strip_is_inside_home_so_it_hides_on_start_and_returns_on_change_topic():
    home = _by_id("home")
    assert home in list(_strip().ancestors())
    assert re.search(r"""getElementById\(\s*["']home["']\s*\)\.style\.display\s*=\s*["']none["']""", _fn_body("startSession"))
    assert re.search(r"""getElementById\(\s*["']home["']\s*\)\.style\.display\s*=\s*["']["']""", HTML)
    for sel, props in _strip_rules():
        assert "!important" not in props.get("display", "")


# ---------- failure case: no numbered markers ----------
def test_no_numbered_markers_shown():
    ol_style = _strip().attrs.get("style", "")
    declared = {}
    for _, p in _strip_rules():
        declared.update(p)
    assert declared.get("list-style", declared.get("list-style-type", "")).split()[0:1] in (["none"],) or \
        "none" in declared.get("list-style-type", ""), "list markers must be removed"
    assert "list-style" in ol_style or declared
    css = " ".join(f"{s}{{{';'.join(f'{k}:{v}' for k, v in p.items())}}}" for s, p in _strip_rules())
    assert "counter" not in css
    assert "content" not in css or not re.search(r"content:\s*[^;]*(counter|\d)", css)
    for s in _steps():
        t = _text(s).lower()
        assert not re.match(r"\W*\d", t)
        assert "step" not in t.split()


# ---------- design decision ----------
def test_design_decision_records_pitch_lives_on_the_board_not_a_cover_page():
    text = DECISIONS.read_text(encoding="utf-8")
    entries = re.split(r"(?m)^## ", text)
    hits = [e for e in entries if "#75" in e and "cover" in e.lower() and "board" in e.lower()]
    assert hits, "no DESIGN_DECISIONS entry for #75 (pitch on the board, not a cover page)"
