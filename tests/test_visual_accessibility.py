"""
Offline static checks for issue #62: keyboard / screen-reader / reduced-motion
support in docs/visual/index.html. No browser, no network, no LLM calls.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "docs" / "visual" / "index.html"
HTML = PAGE.read_text(encoding="utf-8")
VOID = {"input", "br", "img", "meta", "link", "hr", "path", "circle", "rect", "line", "use", "stop"}


class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children, self.text = [], ""

    def descendants(self):
        for c in self.children:
            yield c
            yield from c.descendants()

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _El("root", [], None)
        self.cur = self.root
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        el = _El(tag, attrs, self.cur)
        self.cur.children.append(el)
        if tag not in VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_El(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        c = self.cur
        while c is not self.root and c.tag != tag:
            c = c.parent
        if c is not self.root:
            self.cur = c.parent

    def handle_data(self, data):
        self.cur.text += data


def _dom():
    p = _Parser()
    p.feed(HTML)
    return p.root


def _all():
    return list(_dom().descendants())


def _by_id(i):
    for e in _all():
        if e.attrs.get("id") == i:
            return e
    raise AssertionError(f"#{i} not found")


def _css():
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", HTML, re.S))


def _reduced_motion_css():
    out, css = [], _css()
    for m in re.finditer(r"@media[^{]*prefers-reduced-motion\s*:\s*reduce[^{]*\{", css):
        depth, i = 1, m.end()
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.end():i])
    return "\n".join(out)


def _featured_cards():
    cards = [e for e in _all() if "featured" in e.attrs.get("class", "").split()]
    assert len(cards) == 3
    return cards


def _is_button_or_has(el):
    return el.tag == "button" or any(d.tag == "button" for d in el.descendants())


def test_featured_cards_are_real_buttons():
    for card in _featured_cards():
        assert _is_button_or_has(card)


def test_featured_buttons_start_the_same_session_as_click():
    for i, card in enumerate(_featured_cards()):
        btns = [card] if card.tag == "button" else [d for d in card.descendants() if d.tag == "button"]
        handlers = " ".join(b.attrs.get("onclick", "") for b in btns + list(card.ancestors()))
        assert f"runFeatured({i})" in handlers
        # Enter/Space come free from <button>; extra key handlers would double-start.
        assert not any(k in b.attrs for b in btns for k in ("onkeydown", "onkeyup", "onkeypress"))


def test_no_onclick_on_div_or_span():
    for e in _all():
        if e.tag in ("div", "span"):
            assert "onclick" not in e.attrs, f"<{e.tag}> has onclick"
    # Also dynamically built markup in JS strings.
    assert not re.search(r"<(div|span)\b[^>]*\bonclick=", HTML)
    assert not re.search(r"createElement\(\s*[\"'](div|span)[\"']\s*\)[^;]*\.onclick", HTML)


def test_focus_visible_styles_exist_and_outline_never_dropped():
    css = _css()
    assert ":focus-visible" in css
    assert re.search(r":focus-visible[^{]*\{[^}]*outline", css)
    for sel in ("button", "a", "input", ".chip"):
        assert re.search(rf"(^|[\s,}}]){re.escape(sel)}:focus-visible", css), sel
    # Any rule removing the outline must itself be (or be paired with) a visible replacement.
    for m in re.finditer(r"([^{}]+)\{([^}]*outline\s*:\s*(none|0)\b[^}]*)\}", css):
        body = m.group(2)
        assert "box-shadow" in body or "border" in body, f"outline removed in {m.group(1).strip()}"


def test_status_and_thinking_are_polite_live_regions():
    assert _by_id("status").attrs.get("aria-live") == "polite"
    assert _by_id("thinking-text").attrs.get("aria-live") == "polite"


def test_trace_is_not_a_live_region():
    trace = _by_id("trace")
    assert "aria-live" not in trace.attrs
    assert trace.attrs.get("role") not in ("log", "status", "alert")
    for a in trace.ancestors():
        assert a.attrs.get("aria-live") in (None, "off")


def test_logo_and_decorative_icons_hidden_from_screen_readers():
    logo = next(e for e in _all() if "logo" in e.attrs.get("class", "").split())
    assert "🎓" in logo.text or any(d.tag == "svg" for d in logo.descendants())
    assert logo.attrs.get("aria-hidden") == "true" or any(
        a.attrs.get("aria-hidden") == "true" for a in logo.ancestors())
    for e in _all():
        if "play" in e.attrs.get("class", "").split() and "▶" in e.text:
            assert e.attrs.get("aria-hidden") == "true"


def test_reduced_motion_stops_looping_animations():
    rm = _reduced_motion_css()
    assert rm, "no prefers-reduced-motion: reduce block"
    for sel in (".orb", ".caret", ".fedge", ".fnode", ".gnode", ".jstep", ".stream-card"):
        assert sel in rm, f"{sel} not covered"
    assert re.search(r"animation(-duration)?\s*:\s*(none|0(\.0+)?s?|\.?0*1ms)", rm)
    # pulse dots and spinner (the elements using pulse/spin keyframes)
    css = _css()
    for kf in ("pulse", "spin"):
        users = re.findall(rf"([^{{}}]+)\{{[^}}]*animation:[^;}}]*\b{kf}\b", css)
        assert users
        for sel in users:
            first = sel.strip().split(",")[0].strip().split()[-1].split(":")[0]
            assert first.split(".")[-1] in rm or first in rm, f"{kf} user {first} not covered"


def test_no_transition_all():
    assert not re.search(r"transition\s*:\s*all\b", _css())
    assert not re.search(r"transition-property\s*:\s*all\b", _css())


def test_keyboard_start_of_featured_cannot_double_start():
    # Cards are plain buttons routed through runFeatured -> startSession, and the
    # card row is hidden / start disabled once a session runs, same as for a click.
    m = re.search(r"function startSession\(\)\s*\{(.*?)\n\}", HTML, re.S)
    assert m
    body = m.group(1)
    assert 'getElementById("start").disabled = true' in body
    assert '.featured-row").style.display = "none"' in HTML
    guard = re.search(r"function runFeatured\(i\)\s*\{(.*?)\n\}", HTML, re.S).group(1)
    assert "startSession()" in guard
    # keyboard path must not bypass: no separate key handler calling startSession
    assert not re.search(r"keydown[^;]*(runFeatured|startSession)", HTML)


def test_tab_order_never_hits_hidden_elements():
    dom = _dom()
    dom_all = list(dom.descendants())
    domain = _by_id("domain")
    assert (domain.attrs.get("type") == "hidden" or "hidden" in domain.attrs
            or domain.attrs.get("tabindex") == "-1"
            or "display:none" in domain.attrs.get("style", "").replace(" ", ""))
    for e in dom_all:
        ti = e.attrs.get("tabindex")
        assert ti is None or int(ti) <= 0, "positive tabindex creates a tab trap"

