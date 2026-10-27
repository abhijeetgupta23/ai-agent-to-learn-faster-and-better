"""
Offline static checks for issue #68: the home screen asks one question.
Reads docs/visual/index.html only. No browser, no network, no LLM calls.
"""

from __future__ import annotations

import re

from test_visual_accessibility import HTML, _css, _dom

REPLAY_RE = re.compile(r"runFeatured\((\d)\)")


# ---------- helpers ----------
_ELEMENTS = list(_dom().descendants())  # one parse, so identity and order are stable


def _all():
    return list(_ELEMENTS)


def _by_id(i):
    for e in _ELEMENTS:
        if e.attrs.get("id") == i:
            return e
    raise AssertionError(f"#{i} not found")


def _text(el):
    return (el.text + "".join(_text(c) for c in el.children)).strip()


def _order(el):
    return next(i for i, e in enumerate(_all()) if e is el)


def _rules(css=None):
    """[(selector, {prop: value})] for every flat rule, media nesting ignored."""
    css = re.sub(r"/\*.*?\*/", "", css if css is not None else _css(), flags=re.S)
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        props = {}
        for decl in body.split(";"):
            if ":" in decl:
                k, v = decl.split(":", 1)
                props[k.strip().lower()] = v.strip().lower()
        for s in sel.split(","):
            out.append((" ".join(s.split()), props))
    return out


def _phone_css():
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    out = []
    for m in re.finditer(r"@media[^{]*max-width\s*:\s*(\d+)px[^{]*\{", css):
        if int(m.group(1)) > 600:
            continue
        depth, i = 1, m.end()
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[m.end():i])
    return "\n".join(out)


def _declared(selectors):
    merged = {}
    for sel, props in _rules():
        if sel in selectors:
            merged.update(props)
    return merged


def _statically_hidden(el):
    for e in [el, *el.ancestors()]:
        if "hidden" in e.attrs:
            return True
        if re.search(r"display\s*:\s*none", e.attrs.get("style", "")):
            return True
        names = [f"#{e.attrs['id']}"] if e.attrs.get("id") else []
        names += [f".{c}" for c in e.attrs.get("class", "").split()]
        names += [e.tag + n for n in list(names)]
        for sel, props in _rules():
            if sel in names and props.get("display") == "none":
                return True
    return False


def _fn_body(name):
    m = re.search(r"function\s+" + name + r"\s*\([^)]*\)\s*\{", HTML)
    assert m, f"function {name} not found"
    depth, i = 1, m.end()
    while depth and i < len(HTML):
        depth += {"{": 1, "}": -1}.get(HTML[i], 0)
        i += 1
    return HTML[m.end():i]


def _replay_buttons():
    found = {}
    for e in _all():
        for i in REPLAY_RE.findall(e.attrs.get("onclick", "")):
            found[int(i)] = e
    assert sorted(found) == [0, 1, 2]
    return [found[i] for i in range(3)]


def _start():
    return _by_id("start")


def _question():
    hs = [e for e in _all() if e.tag in ("h1", "h2", "h3") and "what do you want to learn" in _text(e).lower()]
    assert len(hs) == 1
    return hs[0]


def _map_svg():
    cands = [
        e for e in _all()
        if e.tag == "svg" and e.attrs.get("role") == "img" and e.attrs.get("id") != "flowchart"
    ]
    assert len(cands) == 1, "expected exactly one role=img concept-map svg"
    return cands[0]


def _subject_rules():
    return {"#domain-chips .chip", "#domain-chips button", "#domain-chips > button", ".chip"}


# ---------- one main action ----------
def test_exactly_one_primary_button_start_learning():
    prim = [e for e in _all() if e.tag == "button" and "primary" in e.attrs.get("class", "").split()]
    assert len(prim) == 1
    assert "start learning" in _text(prim[0]).lower()
    assert prim[0].attrs.get("id") == "start"


def test_question_is_first_heading_after_the_brand():
    heads = [e for e in _all() if e.tag in ("h1", "h2", "h3")]
    assert "what do you want to learn" in _text(heads[1]).lower()


def test_header_is_a_slim_bar_with_nav_and_no_long_blurb():
    header = next(e for e in _all() if e.tag == "header")
    ids = {d.attrs.get("id") for d in header.descendants()}
    assert {"nav-learn", "nav-evals"} <= ids
    for p in (d for d in header.descendants() if d.tag == "p"):
        assert len(_text(p)) <= 60, "header still carries the long subtitle"


# ---------- left-aligned ----------
def test_home_intro_is_left_aligned():
    q = _question()
    names = set()
    for e in [q, *q.ancestors()]:
        if e.attrs.get("id"):
            names.add(f"#{e.attrs['id']}")
        names.update(f".{c}" for c in e.attrs.get("class", "").split())
        assert "center" not in e.attrs.get("style", "")
    for sel, props in _rules():
        if props.get("text-align") == "center":
            assert not any(n in sel for n in names if n not in (".wrap",)), sel
            assert not re.search(r"\.(setup|home|intro)\b|#setup", sel), sel


# ---------- subject list ----------
def test_subjects_are_a_plain_list_not_cards():
    d = _declared(_subject_rules())
    assert d, "no style rule for the subject buttons"
    bg = d.get("background", d.get("background-color", "none"))
    assert bg in ("none", "transparent", "unset", "inherit", "0", "initial")
    border = d.get("border", "none")
    assert border in ("none", "0", "0 none", "unset", "initial") or "transparent" in border
    assert d.get("box-shadow", "none") in ("none", "0", "unset")


def test_subject_buttons_are_at_least_44px_tall():
    d = _declared(_subject_rules())
    h = d.get("min-height") or d.get("height") or ""
    m = re.match(r"(\d+(?:\.\d+)?)px", h)
    assert m and float(m.group(1)) >= 44


def test_subjects_are_real_buttons_with_aria_pressed():
    assert 'createElement("button")' in HTML
    assert len(re.findall(r"aria-pressed", HTML)) >= 3  # build, click, replay select
    assert re.search(r"""setAttribute\(\s*["']aria-pressed["']""", HTML)
    # Chosen item has a visible marker beyond colour: tick or outline.
    chosen = [p for s, p in _rules() if re.search(r"aria-pressed=.?true", s)]
    assert any(k in p for p in chosen for k in ("outline", "content", "border", "box-shadow"))


def test_runFeatured_and_click_keep_aria_pressed_in_sync():
    assert "aria-pressed" in _fn_body("runFeatured") or "aria-pressed" in HTML.split("initChips")[1][:900]
    assert "aria-pressed" in HTML.split("initChips")[1][:900]


def test_subject_list_is_two_columns_also_on_phone():
    d = _declared({"#domain-chips", ".chips"})
    cols = d.get("grid-template-columns", "")
    assert re.match(r"(repeat\(\s*2\b|1fr 1fr|minmax\(0,\s*1fr\)\s+minmax\(0,\s*1fr\))", cols), cols
    for sel, props in _rules(_phone_css()):
        if sel in ("#domain-chips", ".chips"):
            c = props.get("grid-template-columns")
            assert c is None or re.match(r"(repeat\(\s*2\b|1fr 1fr)", c), c


# ---------- promise ----------
def test_promise_is_one_short_sentence():
    q = _question()
    sibs = q.parent.children
    p = next(s for s in sibs[sibs.index(q) + 1:] if s.tag == "p")
    t = _text(p)
    assert 0 < len(t) <= 120
    assert len(re.findall(r"[.!?](\s|$)", t)) <= 1


# ---------- concept map ----------
def test_concept_map_svg_has_text_alternative_and_marks_the_gap():
    svg = _map_svg()
    label = svg.attrs.get("aria-label", "")
    assert label.strip() and "gap" in label.lower()
    assert svg.attrs.get("aria-hidden") != "true"
    assert any(d.tag in ("circle", "ellipse", "path", "rect") for d in svg.descendants())


def test_concept_map_makes_no_network_request():
    svg = _map_svg()
    for d in [svg, *svg.descendants()]:
        assert d.tag not in ("image", "script", "foreignobject")
        for k in ("href", "xlink:href", "src"):
            assert not re.match(r"(https?:)?//", d.attrs.get(k, ""))
    assert "url(http" not in _text(svg)


def test_concept_map_sits_after_start_button_for_phone():
    assert _order(_map_svg()) > _order(_start())


def test_concept_map_scales_down_to_390px():
    svg = _map_svg()
    assert svg.attrs.get("viewBox") or svg.attrs.get("viewbox")
    w = svg.attrs.get("width", "")
    assert w in ("", "100%") or (w.isdigit() and int(w) <= 340)


# ---------- replays ----------
def test_replays_are_after_start_under_watch_a_replay_heading():
    heads = [e for e in _all() if e.tag in ("h2", "h3", "h4") and "watch a replay" in _text(e).lower()]
    assert len(heads) == 1
    assert _order(heads[0]) > _order(_start())
    for b in _replay_buttons():
        assert _order(b) > _order(heads[0])
        assert b.tag == "button"


def test_replays_are_text_rows_not_cards():
    d = _declared({".featured"})
    assert d, "no style rule for the replay rows"
    assert d.get("background", "none") in ("none", "transparent")
    assert d.get("box-shadow", "none") == "none"
    border = d.get("border", "none")
    assert border in ("none", "0") or "transparent" in border
    row = _declared({".featured-row"})
    assert "repeat(3" not in row.get("grid-template-columns", "")


def test_replay_buttons_still_start_the_same_replays():
    for i in range(3):
        assert f"runFeatured({i})" in HTML
    body = _fn_body("runFeatured")
    assert "startSession()" in body
    assert re.search(r"""getElementById\(\s*["']user["']\s*\)\.value\s*=\s*f\.user_id""", body)


# ---------- no empty panels ----------
def test_brain_and_feed_hidden_before_a_session():
    assert _statically_hidden(_by_id("brain"))
    assert _statically_hidden(_by_id("feed"))


def test_start_reveals_brain_and_feed():
    body = _fn_body("startSession")
    assert re.search(
        r"hidden\s*=\s*false|removeAttribute\(\s*[\"']hidden|"
        r"classList\.(add|remove|toggle)\(\s*[\"'][\w-]*(start|session|run|live|show|hid|reveal)",
        body,
    )


# ---------- no name UI ----------
def test_no_name_ui_and_learner_id_is_a_hidden_alice_default():
    user = _by_id("user")
    assert user.tag == "input"
    assert user.attrs.get("type") == "hidden"
    assert user.attrs.get("value") == "alice"
    assert not [e for e in _all() if e.tag == "label" and e.attrs.get("for") == "user"]
    visible_text_inputs = [
        e for e in _all()
        if e.tag == "input"
        and e.attrs.get("type", "text") in ("text", "search")
        and (e.attrs.get("id") == "user" or e.attrs.get("name") in ("user", "name", "username"))
    ]
    assert not visible_text_inputs
    assert "learning as" not in HTML.lower()
    change = [e for e in _all() if e.tag in ("button", "a") and _text(e).lower() == "change"]
    assert not change


def test_change_topic_control_stays_in_session_bar():
    assert any(
        e.tag == "button" and "change topic" in _text(e).lower() for e in _all()
    )


def test_start_session_reads_user_and_run_featured_sets_it():
    assert re.search(r"""getElementById\(\s*["']user["']\s*\)\.value""", _fn_body("startSession"))
    assert re.search(
        r"""getElementById\(\s*["']user["']\s*\)\.value\s*=\s*f\.user_id""",
        _fn_body("runFeatured"),
    )


# ---------- failure case: running session ----------
def test_replays_and_start_stay_disabled_while_session_runs():
    body = _fn_body("startSession")
    assert re.search(r"getElementById\(\s*[\"']start[\"']\s*\)\.disabled\s*=\s*true", body)
    assert "setFeaturedEnabled(false)" in body
    guard = _fn_body("runFeatured")
    assert re.search(r"getElementById\(\s*[\"']start[\"']\s*\)\.disabled", guard)
    enabler = _fn_body("setFeaturedEnabled")
    sel = re.search(r"querySelectorAll\(\s*[\"']([^\"']+)[\"']", enabler).group(1)
    for b in _replay_buttons():
        classes = b.attrs.get("class", "").split()
        assert any(sel == f".{c}" for c in classes) or "runFeatured" in sel
