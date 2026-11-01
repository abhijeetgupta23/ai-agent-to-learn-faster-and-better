"""
Offline static checks for issue #73: the board becomes the page (new home and
lesson screens). Reads docs/visual/index.html only. No browser, no network,
no LLM calls, no server.

Where the issue gives a choice ("links or buttons", any class name), the tests
look at behaviour (text, handlers, computed CSS from the stylesheet) rather
than at one particular class name.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from test_visual_accessibility import HTML
from test_visual_home import (
    _all,
    _by_id,
    _fn_body,
    _order,
    _phone_css,
    _rules,
    _start,
    _statically_hidden,
    _text,
)
from test_visual_theme import CSS_NC, MARKUP, SCRIPT, _lum, _ratio, _resolve, _root_vars

ROOT = Path(__file__).resolve().parent.parent
HEADLINE = "learn the missing piece first."


# ---------- CSS helpers ----------
def _media_blocks(css):
    """[(query, inner_css, start, end)] for every top-level @media block."""
    out = []
    for m in re.finditer(r"@media([^{]*)\{", css):
        depth, i = 1, m.end()
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append((m.group(1).strip(), css[m.end():i - 1], m.start(), i))
    return out


def _base_css():
    css = CSS_NC
    for _q, _inner, s, e in sorted(_media_blocks(css), key=lambda b: -b[2]):
        css = css[:s] + css[e:]
    return css


def _media_inner(pattern):
    return "\n".join(inner for q, inner, _s, _e in _media_blocks(CSS_NC) if re.search(pattern, q))


def _phone_effective_rules():
    return _rules(_base_css() + "\n" + _phone_css())


def _spec(compound):
    return (
        len(re.findall(r"#[\w-]+", compound)),
        len(re.findall(r"\.[\w-]+", compound)),
        len(re.findall(r"(?:^|[\s>+~])[a-z][\w-]*", compound)),
    )


def _matches(compound, tag, classes, ident):
    if ":" in compound or "[" in compound:
        return False
    toks = re.findall(r"#[\w-]+|\.[\w-]+|[\w-]+|\*", compound)
    if not toks:
        return False
    for t in toks:
        if t == "*":
            continue
        if t.startswith("#"):
            if t[1:] != ident:
                return False
        elif t.startswith("."):
            if t[1:] not in classes:
                return False
        elif t != tag:
            return False
    return True


def _props(tag="", classes=(), ident="", rules=None):
    """Merged declarations of every rule whose LAST compound matches (specificity, then source order)."""
    rules = _rules() if rules is None else rules
    hits = []
    for n, (sel, props) in enumerate(rules):
        last = re.split(r"\s*[>+~]\s*|\s+", sel.strip())[-1]
        if _matches(last, tag, set(classes), ident):
            hits.append((_spec(last), n, props))
    merged = {}
    for _s, _n, props in sorted(hits, key=lambda h: (h[0], h[1])):
        merged.update(props)
    return merged


def _props_of(el, rules=None):
    return _props(el.tag, el.attrs.get("class", "").split(), el.attrs.get("id", ""), rules)


def _props_with_ancestors(el):
    """Declarations that apply to el or any ancestor (background/colour lookups)."""
    return [(e, _props_of(e)) for e in [el, *el.ancestors()] if getattr(e, "tag", "") != "root"]


def _px_values(val):
    nums = []
    for n, unit in re.findall(r"([\d.]+)(px|rem|em)\b", val or ""):
        nums.append(float(n) * (1 if unit == "px" else 16))
    return nums


def _is_chalk(val):
    val = val or ""
    if "var(--chalk)" in val.replace(" ", ""):
        return True
    return _resolve(val) == _root_vars().get("--chalk", "#none").lower()


def _bg(props):
    return props.get("background", props.get("background-color", ""))


def _uses_board(val):
    return "var(--board)" in (val or "").replace(" ", "")


def _section_with_heading(text):
    heads = [e for e in _all() if e.tag in ("h1", "h2", "h3") and text in _text(e).lower()]
    assert len(heads) == 1, f"expected one heading '{text}'"
    sec = next((a for a in heads[0].ancestors() if a.tag == "section"), None)
    assert sec is not None, f"heading '{text}' is not inside a <section>"
    return heads[0], sec


def _js_buttons():
    """(variable-name, class tokens) for every button the script creates, plus <button class=...> templates."""
    out = []
    for m in re.finditer(r"""(?:const|let|var)\s+(\w+)\s*=\s*document\.createElement\(\s*["']button["']\s*\)""", SCRIPT):
        tail = SCRIPT[m.end():m.end() + 400]
        c = re.search(rf"""\b{m.group(1)}\.className\s*=\s*["']([^"']+)["']""", tail)
        out.append((m.group(1), c.group(1).split() if c else []))
    for m in re.finditer(r"""<button\b[^>]*\bclass=["']([^"']+)["']""", SCRIPT):
        out.append(("tpl", m.group(1).split()))
    return out


def _button_classes():
    classes = set()
    for e in _all():
        if e.tag == "button":
            classes.update(e.attrs.get("class", "").split())
    for _n, c in _js_buttons():
        classes.update(c)
    return classes


# ---------- home: hero = the board ----------
def test_home_has_one_h1_with_the_headline():
    h1s = [e for e in _all() if e.tag == "h1"]
    assert len(h1s) == 1, "the home must have exactly one h1 (the wordmark must not be an h1)"
    assert _text(h1s[0]).lower() == HEADLINE


def test_h1_sits_in_a_full_width_section_on_the_board_colour():
    h1 = next((e for e in _all() if e.tag == "h1" and HEADLINE in _text(e).lower()), None)
    assert h1 is not None, "the headline h1 is missing"
    secs = [(e, p) for e, p in _props_with_ancestors(h1) if e.tag == "section"]
    assert secs, "h1 is not inside a <section>"
    sec, props = secs[0]
    assert _uses_board(_bg(props)), "hero section background must be var(--board)"
    assert props.get("max-width", "none") in ("none", "100%"), "hero must be full width"
    assert any(d is _start() for d in sec.descendants()), "#start must be inside the hero"


def test_start_is_the_only_chalk_filled_button_and_has_no_arrow():
    start = _start()
    assert start.tag == "button"
    assert _text(start) == "Start learning"
    assert "→" not in _text(start)
    chalk = [
        e for e in _all()
        if e.tag in ("button", "a", "input") and _is_chalk(_bg(_props_of(e)))
    ]
    assert chalk == [start], f"expected #start to be the only chalk-filled control, got {len(chalk)}"


def test_hero_has_promise_question_label_and_no_account_note():
    h1 = next(e for e in _all() if e.tag == "h1")
    sibs = h1.parent.children
    p = next((s for s in sibs[sibs.index(h1) + 1:] if s.tag == "p"), None)
    assert p is not None, "no promise sentence after the h1"
    t = _text(p)
    assert 0 < len(t.split()) <= 25, "promise must be at most 25 words"
    assert len(re.findall(r"[.!?](\s|$)", t)) <= 1, "promise must be one sentence"
    labels = [e for e in _all() if _text(e).lower() == "what do you want to learn?" and not e.children]
    assert labels, "the label 'What do you want to learn?' is missing"
    assert any(_text(e) == "No account needed." for e in _all()), "'No account needed.' note missing"
    note = next(e for e in _all() if _text(e) == "No account needed.")
    assert _order(note) > _order(_start())


# ---------- subjects: names plus idea counts ----------
def _domain_counts():
    block = re.search(r"DOMAINS\s*=\s*\[(.*?)\];", SCRIPT, re.S).group(1)
    counts = {}
    for entry in re.findall(r"\{([^{}]*)\}", block):
        ident = re.search(r"""id\s*:\s*["'](\w+)["']""", entry).group(1)
        nums = re.findall(r"""\b(?!id\b)\w+\s*:\s*(\d+)\b""", entry)
        counts[ident] = int(nums[0]) if nums else None
    return counts


def test_every_subject_carries_an_idea_count():
    counts = _domain_counts()
    assert len(counts) == 8
    assert all(isinstance(n, int) and n > 0 for n in counts.values()), counts


def test_idea_count_matches_the_number_of_concepts_in_the_domain():
    graph = json.loads((ROOT / "evals" / "golden" / "graphs" / "cognitive_biases.json").read_text())
    assert _domain_counts()["cognitive_biases"] == len(graph["nodes"])


def test_subject_button_shows_its_count_as_ideas_and_phone_hides_it():
    body = HTML.split("(function initChips()")[1].split("})();")[0]
    assert re.search(r"\bideas?\b", body), "initChips must print the count with the word 'ideas'"
    classes = set(re.findall(r"""(?:className\s*=|classList\.add\()\s*["']([\w -]+)["']""", body)) - {"chip"}
    classes |= {c for chunk in re.findall(r"""class=["']([\w -]+)["']""", body) for c in chunk.split()}
    classes.discard("chip")
    assert classes, "the count must sit in its own element with a class"
    hidden = [
        sel for sel, p in _rules(_phone_css())
        if p.get("display") == "none" and any(f".{c}" in sel for c in classes)
    ]
    assert hidden, "idea counts must be hidden at phone width"


def test_chosen_subject_has_a_chalk_left_edge():
    chosen = [p for s, p in _rules() if re.search(r"aria-pressed=.?true", s)]
    assert chosen
    blob = " ".join(f"{k}:{v}" for p in chosen for k, v in p.items())
    assert "var(--chalk)" in blob.replace(" ", ""), "chosen row needs a chalk edge"


# ---------- hero map ----------
def _hero_maps():
    _h, sec = _section_with_heading(HEADLINE)
    return [e for e in sec.descendants() if e.tag == "svg" and e.attrs.get("role") == "img"]


def _alt_text(svg):
    parts = [svg.attrs.get("aria-label", "")]
    parts += [_text(d) for d in svg.descendants() if d.tag == "title"]
    return " ".join(parts).lower()


def test_hero_map_is_inline_svg_with_text_alternative_marking_the_gap():
    maps = _hero_maps()
    assert maps, "no role=img svg in the hero"
    for svg in maps:
        assert "gap" in _alt_text(svg)
        assert svg.attrs.get("aria-hidden") != "true"
        assert svg.attrs.get("viewBox") or svg.attrs.get("viewbox")
    labelled = [s for s in maps if s.attrs.get("aria-labelledby")]
    for s in labelled:
        assert any(d.attrs.get("id") == s.attrs["aria-labelledby"] for d in s.descendants())


def test_hero_map_makes_no_network_request():
    for svg in _hero_maps():
        for d in [svg, *svg.descendants()]:
            assert d.tag not in ("image", "script", "foreignobject")
            for k in ("href", "xlink:href", "src"):
                assert not re.match(r"(https?:)?//", d.attrs.get(k, ""))
    assert _hero_maps(), "no hero map to check"


def test_hero_map_has_the_gap_note():
    notes = " ".join(_text(d) for m in _hero_maps() for d in m.descendants()).lower()
    assert "this is the gap" in notes
    assert "lesson one starts here" in notes


def test_circle_draws_in_once_and_never_under_reduced_motion():
    maps = _hero_maps()
    classes = {c for m in maps for d in [m, *m.descendants()] for c in d.attrs.get("class", "").split()}
    gap = [c for c in classes if "gap" in c.lower()]
    assert gap, "the circled gap needs a class containing 'gap'"
    sel_hit = lambda sel: any(f".{c}" in sel for c in gap)  # noqa: E731
    allowed = _media_inner(r"prefers-reduced-motion\s*:\s*no-preference")
    assert allowed, "draw-in must live in a prefers-reduced-motion: no-preference block"
    anim = [(s, p) for s, p in _rules(allowed) if sel_hit(s) and "animation" in p]
    assert anim, "no draw-in animation on the gap circle"
    assert all("infinite" not in p["animation"] for _s, p in anim), "the circle draws in once"
    # Outside that block the circle must be fully drawn: no animation, no hidden dash offset.
    outside = _rules(re.sub(re.escape(allowed), "", CSS_NC))
    for s, p in outside:
        if sel_hit(s):
            assert p.get("animation", "none") in ("none",) or "animation" not in p, s
            assert p.get("stroke-dashoffset", "0") in ("0", "0px"), s


def test_phone_shows_a_smaller_three_idea_map_after_the_button():
    maps = _hero_maps()
    assert len(maps) == 2, "expected a full map and a small phone map"
    full, small = sorted(maps, key=lambda m: -len([d for d in m.descendants() if d.tag == "circle"]))
    assert len([d for d in small.descendants() if d.tag == "circle"]) == 3, "the phone map shows 3 ideas"
    assert _order(small) > _order(_start())

    def hides(svg, rules):
        cls = svg.attrs.get("class", "").split()
        return _props("svg", cls, svg.attrs.get("id", ""), rules).get("display") == "none"

    assert hides(full, _phone_effective_rules()), "full map must be hidden on a phone"
    assert not hides(small, _phone_effective_rules()), "small map must show on a phone"
    assert hides(small, _rules(_base_css())), "small map must be hidden on desktop"


# ---------- header ----------
def test_header_holds_three_links_and_no_6_of_6_badge():
    header = next(e for e in _all() if e.tag == "header")
    ids = {d.attrs.get("id") for d in header.descendants()}
    assert {"nav-learn", "nav-evals"} <= ids
    links = [d for d in header.descendants() if d.tag in ("a", "button")]
    texts = [_text(d).lower() for d in links if d.attrs.get("id") or d.tag == "a"]
    assert any("watch a lesson" in t for t in texts)
    assert "how we test it" in _text(_by_id("nav-evals")).lower()
    assert "learn" == _text(_by_id("nav-learn")).lower()
    jump = next(d for d in links if "watch a lesson" in _text(d).lower())
    target = jump.attrs.get("href", "")
    assert target.startswith("#") and len(target) > 1
    assert any(e.attrs.get("id") == target[1:] for e in _all()), "Watch a lesson must jump to a real section"
    assert "6/6" not in MARKUP
    assert "nav-pass" not in HTML and "badge-pass" not in HTML


def test_header_links_are_44px_tall_and_visible_at_390px():
    header = next(e for e in _all() if e.tag == "header")
    links = [d for d in header.descendants() if d.tag in ("a", "button") and (d.attrs.get("id") or d.tag == "a")]
    nav = [d for d in links if d.attrs.get("id") in ("nav-learn", "nav-evals") or "watch a lesson" in _text(d).lower()]
    assert len(nav) == 3
    rules = _phone_effective_rules()
    for el in nav:
        p = _props_of(el, rules)
        assert p.get("display") != "none", _text(el)
        h = max(_px_values(p.get("min-height", "")) + _px_values(p.get("height", "")) or [0])
        assert h >= 44, f"{_text(el)} is {h}px tall at phone width"
    assert not [e for e in _all() if re.search(r"burger|menu-toggle|hamburger", " ".join(e.attrs.values()), re.I)]


def test_the_separate_session_bar_is_gone_and_status_still_announces():
    assert 'id="session-bar"' not in HTML
    status = _by_id("status")
    assert status.attrs.get("aria-live") == "polite"


# ---------- replays ----------
def _replay_section():
    return _section_with_heading("watch it teach alice")


def test_replay_section_follows_the_hero_on_a_darker_paper_step():
    _h, sec = _replay_section()
    assert _order(sec) > _order(_start())
    p = _props_of(sec)
    assert "var(--paper-2)" in _bg(p).replace(" ", ""), "replay field must use the one-step-darker --paper-2"
    assert sec.attrs.get("id"), "the section needs an id for the 'Watch a lesson' link"


def _replay_selectors(sec):
    watch = [e for e in sec.descendants() if e.tag in ("a", "button") and "watch this replay" in _text(e).lower()]
    assert len(watch) == 1, "a separate 'Watch this replay' control is required"
    picks = [e for e in sec.descendants() if e.tag in ("a", "button") and e is not watch[0]]
    return watch[0], picks


def test_three_replay_links_choose_an_excerpt_and_a_separate_control_starts_it():
    _h, sec = _replay_section()
    watch, picks = _replay_selectors(sec)
    assert len(picks) == 3, f"expected 3 replay links, found {len(picks)}"
    seen = set()
    for e in picks:
        blob = " ".join(v for k, v in e.attrs.items() if k not in ("class", "id"))
        seen.update(re.findall(r"(?<!\d)([012])(?!\d)", blob))
    assert seen == {"0", "1", "2"}, "each replay link must identify which replay it is"
    assert "runFeatured(" in watch.attrs.get("onclick", "")
    assert watch.tag == "button"


def test_replay_excerpt_has_learner_tutor_and_a_board_coloured_why_line():
    _h, sec = _replay_section()
    texts = [_text(e) for e in sec.descendants()]
    why = [e for e in sec.descendants() if _text(e).startswith("Why:") and not any(
        _text(c).startswith("Why:") for c in e.children)]
    assert why, "excerpt needs a 'Why:' line"
    assert _uses_board(_bg(_props_of(why[0]))), "the Why line sits on the board colour"
    assert any(t == "Tutor" for t in texts), "excerpt labels the tutor"
    assert len(re.findall(r"\bwhy\s*:", HTML, re.I)) >= 3, "one excerpt per replay (3)"


def test_replay_run_function_is_unchanged():
    body = _fn_body("runFeatured")
    assert "startSession()" in body
    assert re.search(r"""getElementById\(\s*["']user["']\s*\)\.value\s*=\s*f\.user_id""", body)
    assert len(re.findall(r"""user_id\s*:\s*["']demo-""", SCRIPT)) == 3


def test_replay_and_start_stay_disabled_while_a_session_runs():
    _h, sec = _replay_section()
    watch, _picks = _replay_selectors(sec)
    enabler = _fn_body("setFeaturedEnabled")
    sel = re.search(r"querySelectorAll\(\s*[\"']([^\"']+)[\"']", enabler).group(1)
    classes = watch.attrs.get("class", "").split()
    ident = watch.attrs.get("id", "")
    assert any(sel == f".{c}" for c in classes) or (ident and sel == f"#{ident}") or "runFeatured" in sel, (
        "setFeaturedEnabled must cover the 'Watch this replay' control"
    )
    body = _fn_body("startSession")
    assert "setFeaturedEnabled(false)" in body
    assert re.search(r"getElementById\(\s*[\"']start[\"']\s*\)\.disabled\s*=\s*true", body)
    assert re.search(r"getElementById\(\s*[\"']start[\"']\s*\)\.disabled", _fn_body("runFeatured"))


# ---------- proof: results table on the home ----------
def test_results_section_has_sentence_link_and_no_empty_static_table():
    _h, sec = _section_with_heading("every lesson choice is checked")
    link = next(e for e in sec.descendants() if e.tag in ("a", "button") and "see the full results" in _text(e).lower())
    assert "evals" in link.attrs.get("onclick", "") + link.attrs.get("href", "")
    for t in (e for e in sec.descendants() if e.tag == "table"):
        rows = [d for d in t.descendants() if d.tag == "tr" and not any(c.tag == "th" for c in d.children)]
        assert not rows or _statically_hidden(t), "no empty or placeholder table before /evals loads"


def _results_renderer():
    """Body of the function that writes Passed/Failed table rows for the home."""
    names = [m for m in re.finditer(r"function\s+(\w+)\s*\([^)]*\)\s*\{", SCRIPT)]
    for m in names:
        body = _fn_body(m.group(1))
        if "Passed" in body and "Failed" in body:
            return m.group(1), body
    raise AssertionError("no function writes Passed/Failed cells")


def test_home_results_table_has_one_row_per_case_with_passed_or_failed():
    _name, body = _results_renderer()
    assert "<table" in body or 'createElement("table")' in body or "createElement('table')" in body or "<tr" in body
    assert re.search(r"\.cases\b", body)
    assert re.search(r"forEach|\.map\(", body)
    assert re.search(r"\.passed\b", body)
    assert re.search(r"CASE_PLAIN|caseTitle\(|CASE_NAME|CASE_LABEL|humanize\(", body), "case names must be readable"
    assert re.search(r"CASE_CONTEXT|expect", body), "third column: what it had to get right"
    assert "Passed" in body and "Failed" in body


def test_results_failure_says_so_in_one_sentence_with_a_link_and_no_table():
    sentences = [m.start() for m in re.finditer(r"couldn[’']t be loaded|could not be loaded", SCRIPT + MARKUP)]
    assert sentences, "need the sentence 'results couldn't be loaded'"
    assert "results" in (SCRIPT + MARKUP)[max(0, sentences[0] - 80):sentences[0] + 40].lower()
    _name, body = _results_renderer()
    assert re.search(r"cases\.length|!\s*\w*\.?cases|\.cases\s*&&|cases\s*\|\|", body), (
        "empty or missing cases must take the failure path"
    )
    # the fetch failing and the no-cases case both reach the failure message, with a link home to the eval view
    assert re.search(r"fetch\(\s*[\"']/evals[\"']", SCRIPT)
    near = (SCRIPT + MARKUP)[max(0, sentences[0] - 300):sentences[0] + 400]
    assert "showView" in near or "nav-evals" in near or "#evals" in near


def test_results_third_column_hidden_on_phone():
    hidden = [s for s, p in _rules(_phone_css()) if p.get("display") == "none"]
    assert any(re.search(r"nth-child\(3\)|\bt[dh]\b|\bcol\b|hide-phone|\.what", s) for s in hidden)


# ---------- footer ----------
def test_footer_repeats_the_name_very_large_on_the_board_colour():
    foot = next((e for e in _all() if e.tag == "footer"), None)
    assert foot is not None, "the page needs a <footer>"
    assert _uses_board(_bg(_props_of(foot)))
    name = next(d for d in foot.descendants() if _text(d) == "Learn Faster")
    sizes = []
    for e in [name, *name.ancestors()]:
        p = _props_of(e)
        sizes += _px_values(p.get("font-size", "")) + _px_values(p.get("font", ""))
    assert sizes and max(sizes) >= 96, "footer wordmark must be set very large"
    assert any("Open source. About $0.17 a lesson." == _text(d) for d in foot.descendants())


def test_skip_link_and_main_landmark():
    skip = [e for e in _all() if e.tag == "a" and "skip" in e.attrs.get("class", "").split()]
    assert skip and skip[0].attrs.get("href") == "#main"
    assert any(e.tag == "main" and e.attrs.get("id") == "main" for e in _all())


# ---------- lesson: tutor's internals behind a closed <details> ----------
def test_brain_parts_live_in_one_closed_details_titled_see_how_the_tutor_decided():
    det = None
    for ident in ("flowchart", "thinking", "trace"):
        el = _by_id(ident)
        found = next((a for a in el.ancestors() if a.tag == "details"), None)
        assert found is not None, f"#{ident} is not inside a <details>"
        assert det is None or found is det, "the three parts must share one <details>"
        det = found
    assert "open" not in det.attrs, "must be closed by default"
    summary = next(c for c in det.children if c.tag == "summary")
    assert _text(summary) == "See how the tutor decided"


def test_closed_details_still_receive_live_thinking_and_the_full_trace():
    assert _by_id("thinking-text").attrs.get("aria-live") == "polite"
    for fn in ("setThinking", "appendThinking", "renderThinking", "trace"):
        body = _fn_body(fn)
        assert not re.search(r"\.open\b|\bopen\s*=", body), f"{fn} must not depend on the details being open"
    assert "thinking-text" in SCRIPT
    assert "appendChild" in _fn_body("trace") or "insertAdjacent" in _fn_body("trace") or "innerHTML" in _fn_body("trace")


def test_brain_parts_start_hidden_and_a_session_reveals_them():
    for ident in ("feed", "flowchart", "thinking", "trace"):
        assert _statically_hidden(_by_id(ident)), f"#{ident} must be hidden before a session"
    assert _statically_hidden(_by_id("split"))
    assert re.search(r"""getElementById\(\s*["']split["']\s*\)\.hidden\s*=\s*false|\[\s*["']split["']""", _fn_body("startSession"))


# ---------- lesson: why this lesson ----------
def _why_heading():
    heads = [e for e in _all() if e.tag in ("h2", "h3") and _text(e) == "Why this lesson"]
    assert len(heads) == 1, "the board column needs one 'Why this lesson' heading"
    return heads[0]


def test_why_this_lesson_is_visible_without_opening_anything_and_filled_by_gap():
    heads = [_why_heading()]
    assert not any(a.tag == "details" for a in heads[0].ancestors()), "must be visible without opening anything"
    holder = heads[0].parent
    ids = [d.attrs["id"] for d in holder.descendants() if d.attrs.get("id") and d is not heads[0]]
    assert ids, "the reason needs an element with an id"
    start = SCRIPT.index('event === "gap"')
    branch = SCRIPT[start:SCRIPT.index("event ===", start + 20)]
    assert any(f'"{i}"' in branch or f"'{i}'" in branch for i in ids), "the gap event must write the reason"
    assert "rationale" in branch


def test_board_column_sits_beside_the_lesson_and_is_sticky():
    why = _why_heading()
    split = _by_id("split")
    assert any(a is split for a in why.ancestors()), "the board column lives inside #split"
    sticky = [s for s, p in _rules() if p.get("position") == "sticky"]
    assert sticky, "the board column must be position: sticky"
    cols = [p.get("grid-template-columns", "") for s, p in _rules() if p.get("display") == "grid"]
    assert any(len(re.findall(r"\bfr\b|minmax", c)) >= 2 for c in cols), "two-column lesson layout"


def test_phone_puts_why_first_and_keeps_plan_and_details_after_the_lesson():
    why = _why_heading()
    feed = _by_id("feed")
    first_in_dom = _order(why) < _order(feed)
    ordered = any(p.get("order", "").startswith("-") for _s, p in _rules(_phone_css()))
    assert first_in_dom or ordered, "on a phone 'Why this lesson' comes before the lesson"
    for sel, p in _rules(_phone_css()):
        if p.get("display") == "none":
            assert not re.search(r"details|\bol\b|plan|summary", sel), f"phone must not hide the plan or details: {sel}"


# ---------- lesson: plan ----------
def test_plan_is_a_named_ordered_list_with_aria_current_and_no_counts():
    body = _fn_body("renderCurriculum")
    assert "<ol" in body
    assert re.search(r"humanize(?:Concept)?\(\s*s\.concept_id", body), "plan items use readable concept names"
    assert not re.search(r"class=[\"']num[\"']|step_number\}</span>", body), "no step numbers shown"
    mark = _fn_body("markCurriculum")
    assert re.search(r"aria-current", mark) and "step" in mark
    assert re.search(r"removeAttribute\(\s*[\"']aria-current|aria-current[\"']\s*,\s*[\"']?false", mark) or "aria-current" in mark
    assert not re.search(r"""\bStep \$\{|[Ss]tep \d+ of|of \$\{totalSteps\}|class=["']dot""", SCRIPT)


def test_progress_dots_are_gone_from_the_lesson():
    assert "progressDots(" not in _fn_body("renderLesson")
    assert not re.search(r"\.dot\b", CSS_NC) or "progressDots" not in SCRIPT


def test_plan_has_a_chalk_left_edge_on_the_current_step():
    cur = [p for s, p in _rules() if re.search(r"aria-current", s)]
    assert cur, "style the current plan step"
    assert any("var(--chalk)" in " ".join(p.values()).replace(" ", "") for p in cur)


# ---------- lesson: title, body, answers ----------
def test_lesson_title_is_the_page_h1_and_subject_is_small_text():
    body = _fn_body("renderLesson")
    assert "<h1" in body
    assert not re.search(r"<h3>\$\{esc\(a\.title\)\}", body)
    assert re.search(r"DOMAINS|domain|subject", body, re.I), "the subject name appears above the title"


_LESSON_SELECTORS = {".lesson", ".lesson p", ".body", ".body p", ".lesson .body", "#feed .body", "#feed .lesson"}


def test_lesson_body_is_18px_with_line_height_and_a_narrow_column():
    rules = [(s, p) for s, p in _rules() if s in _LESSON_SELECTORS]
    sizes = [px for _s, p in rules for px in _px_values(p.get("font-size", ""))]
    assert sizes and min(sizes) >= 18, sizes
    heights = []
    for _s, p in rules:
        lh = p.get("line-height", "")
        if re.fullmatch(r"[\d.]+", lh):
            heights.append(float(lh))
        elif lh.endswith("px"):
            heights.append(float(lh[:-2]) / 18)
    assert heights and min(heights) >= 1.5, heights
    widths = []
    for s, p in _rules():
        if s in _LESSON_SELECTORS | {"#feed", ".feed", "main.lesson", ".lesson-col", ".lesson-column"}:
            for v in re.findall(r"([\d.]+)(px|ch|rem|em)", p.get("max-width", "")):
                n, unit = float(v[0]), v[1]
                widths.append(n if unit == "px" else n * 16 if unit in ("rem", "em") else n * 9)
    assert widths and max(widths) <= 760, widths


def _respond_body():
    return _fn_body("addRespond")


def test_reading_and_socratic_lessons_have_one_main_button_and_one_quiet_one():
    body = _respond_body()
    btns = re.findall(r"<button\b([^>]*)>(.*?)</button>", body, re.S)
    assert len(btns) == 2, f"expected two answer buttons, found {len(btns)}"
    texts = [re.sub(r"<[^>]+>", "", t).strip() for _a, t in btns]
    assert texts[0].replace("’", "'") == "I've got it"
    assert texts[1].replace("’", "'") == "I'm stuck, explain it differently"
    assert "submitResponse(true" in btns[0][0] and "submitResponse(false" in btns[1][0]
    assert "getNotes()" in btns[0][0] and "getNotes()" in btns[1][0]
    classes = [re.search(r"""class=["']([^"']+)""", a).group(1).split() for a, _t in btns]
    main, quiet = (_props("button", c) for c in classes)
    assert _is_chalk(_bg(main)), "'I've got it' is the chalk-filled button"
    assert not _is_chalk(_bg(quiet)), "the stuck button is quiet"
    for p in (main, quiet):
        assert max(_px_values(p.get("min-height", "")) + _px_values(p.get("height", "")) or [0]) >= 44
    assert "resp-notes" in body, "the optional note box stays"


def test_answer_request_body_is_unchanged():
    body = _fn_body("submitResponse")
    assert re.search(r"/agent/sessions/\$\{currentSessionId\}/respond_stream", body)
    assert re.search(r"\{\s*correct\s*,\s*notes\s*\}", body)


def test_interactive_options_are_full_width_rows_at_least_56px_tall():
    assert 'className = "opt"' in _fn_body("renderQuiz")
    opt = _props("button", ["opt"])
    assert max(_px_values(opt.get("min-height", "")) + _px_values(opt.get("height", "")) or [0]) >= 56
    assert opt.get("width") == "100%" or opt.get("display") in ("flex", "grid", "block")


def test_socratic_turns_are_labelled_tutor_and_you_with_a_tone_step_for_the_learner():
    body = _fn_body("renderLesson")
    assert '"Tutor"' in body and '"You"' in body
    you = [p for s, p in _rules() if re.search(r"(\.turn\.user|\.turn\.you|\.you|\.user)\b", s)]
    assert any("var(--paper-2)" in _bg(p).replace(" ", "") for p in you), "learner turns sit on the tone step"


# ---------- change topic ----------
def test_change_topic_goes_fully_home():
    change = [e for e in _all() if e.tag == "button" and "change topic" in _text(e).lower()]
    assert change and "resetToSetup()" in change[0].attrs.get("onclick", "")
    body = _fn_body("resetToSetup")
    assert re.search(r"getElementById\(\s*[\"']home[\"']\s*\)\.(style\.display\s*=\s*[\"']{2}|hidden\s*=\s*false)", body)
    assert re.search(r"getElementById\(\s*[\"']split[\"']\s*\)\.(hidden\s*=\s*true|style\.display\s*=\s*[\"']none)", body)
    assert "session-bar" not in body
    why = _why_heading()
    assert any(a.attrs.get("id") == "split" for a in why.ancestors()), "the board column is inside the area reset hides"
    for ident in ("feed",):
        assert re.search(rf"getElementById\(\s*[\"']{ident}[\"']\s*\)", body), f"reset must clear #{ident}"
    assert "setFeaturedEnabled(true)" in body or "disabled = false" in body, "replays and Start usable again"


# ---------- look of the whole page ----------
def test_no_border_radius_on_buttons():
    classes = _button_classes()
    for sel, p in _rules():
        if "border-radius" not in p:
            continue
        last = re.split(r"\s*[>+~]\s*|\s+", sel)[-1]
        is_button = "button" in last or any(f".{c}" in last for c in classes)
        if is_button:
            assert p["border-radius"] in ("0", "0px", "none"), f"{sel}: {p['border-radius']}"


def test_no_resting_box_shadow_except_a_zero_blur_inset_edge():
    for sel, p in _rules():
        v = p.get("box-shadow", "none")
        if v in ("none", "0", "unset", "initial", "inherit"):
            continue
        if re.search(r":(hover|focus|focus-visible|active)", sel):
            continue
        # allowed: the chalk left edge, drawn as `inset <x> 0 0 <colour>` (no blur, no spread)
        assert re.match(r"inset\s+-?[\d.]+px\s+0(?:px)?\s+0(?:px)?\s+[^,]+$", v), f"{sel}: {v}"
    assert "drop-shadow" not in CSS_NC


def test_no_gradients_anywhere():
    assert not re.search(r"gradient", HTML, re.I)


def test_no_arrow_in_button_text():
    assert not re.search(r"<button\b[^>]*>[^<]*→", HTML)
    assert not re.search(r"\.textContent\s*=\s*[\"'][^\"']*→", SCRIPT)
    assert not re.search(r"(?:button|btn|cont|b)\.innerHTML\s*=\s*[\"'`][^\"'`]*→", SCRIPT)


def test_no_thin_divider_lines_or_outlined_boxes():
    bad = [m.group(0) for m in re.finditer(r"border[\w-]*\s*:[^;}\"']*\b1px\s+solid[^;}\"']*", HTML)]
    assert not bad, bad[:3]
    assert not re.search(r"border[\w-]*\s*:[^;}]*\b0?\.5px\s+solid", HTML)


def test_no_pill_badges_or_eyebrow_labels():
    for sel, p in _rules():
        br = p.get("border-radius", "")
        for n, unit in re.findall(r"([\d.]+)(px|rem|em)", br):
            assert float(n) * (1 if unit == "px" else 16) < 20, f"{sel}: {br}"
    assert not re.search(r"""class=["'][^"']*\b(pill|badge|eyebrow|kicker|overline)\b""", HTML)
    assert not re.search(r"ev-badge|jscore-pill", HTML)


def test_no_new_third_party_requests():
    # Today's only external host is the KaTeX CDN; fonts stay self-hosted and nothing new is added.
    hosts = set(re.findall(r"""(?:src|href)=["']https?://([^/"']+)""", HTML, re.I))
    hosts |= set(re.findall(r"""url\(\s*["']?https?://([^/"')]+)""", HTML, re.I))
    hosts |= set(re.findall(r"@import[^;]*https?://([^/\"')]+)", HTML, re.I))
    assert hosts <= {"cdn.jsdelivr.net"}, hosts
    assert not re.search(r"fonts\.(googleapis|gstatic)\.com", HTML)


# ---------- colour ----------
def test_paper_2_is_a_slightly_darker_tone_step_than_paper():
    v = _root_vars()
    assert "--paper-2" in v, "add the --paper-2 tone-step token"
    paper = _resolve(v["--paper"])
    p2 = _resolve(v["--paper-2"])
    assert p2 != paper and _lum(p2) < _lum(paper)
    assert _ratio(paper, p2) < 1.3, "a step in tone, not a different colour"


def test_every_text_background_pair_is_at_least_4_5_to_1():
    v = _root_vars()
    pairs = [
        ("--ink", "--paper"), ("--ink", "--paper-2"),
        ("--board", "--paper-2"), ("--board", "--paper"),
        ("--chalk-ink", "--board"), ("--chalk-ink-2", "--board"),
        ("--chalk-ink", "--board-2"), ("--chalk-ink-2", "--board-2"),
        ("--chalk", "--board"), ("--ink", "--chalk"),
    ]
    for a, b in pairs:
        assert a in v and b in v, f"missing token {a if a not in v else b}"
        assert _ratio(_resolve(v[a]), _resolve(v[b])) >= 4.5, (a, b)
    assert _ratio(_resolve(v["--ink-2"]), _resolve(v["--paper-2"])) >= 4.5
    for sel, p in _rules():
        fg, bg = _resolve(p.get("color", "")), _resolve(_bg(p))
        if fg and bg:
            assert _ratio(fg, bg) >= 4.5, f"{sel}: {fg} on {bg}"


# ---------- layout at 360 / 390 / 1440 (static proxies; no browser offline) ----------
def test_headings_fit_two_lines_at_360px_proxy():
    for el in (e for e in _all() if e.tag in ("h1", "h2")):
        if not _text(el):
            continue
        p = _props_of(el)
        sizes = _px_values(re.sub(r"/[\d.]+", "", p.get("font-size", "") or p.get("font", "")))
        fs = min(sizes) if sizes else 18
        per_line = (360 - 32) / (0.5 * fs)
        assert len(_text(el)) <= 2 * per_line, f"'{_text(el)}' at {fs}px may run past two lines at 360px"


def test_two_column_sections_collapse_to_one_column_on_a_phone():
    singles = [
        s for s, p in _rules(_phone_css())
        if re.fullmatch(r"(1fr|minmax\(0,\s*1fr\))", p.get("grid-template-columns", ""))
    ]
    assert len(singles) >= 2, "hero, replay, results and lesson grids must collapse on a phone"
    assert 'name="viewport"' in HTML
    for svg in _hero_maps():
        w = svg.attrs.get("width", "")
        assert w in ("", "100%") or (w.isdigit() and int(w) <= 340)
    assert not re.search(r"overflow-x\s*:\s*hidden", CSS_NC), "hiding sideways scroll is not a fix"
