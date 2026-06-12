"""
Teaching charts via Anthropic code execution (true PTC).

The model WRITES matplotlib code and RUNS it in Anthropic's hosted sandbox;
we retrieve the rendered PNG and hand it back as a data URL. No code executes
on our infrastructure. A missing chart never breaks a lesson — every failure
path returns None and the lesson renders without it.
"""

from __future__ import annotations

import base64

from src.llm import generate_chart_png
from src.schemas import ConceptNode

_INSTRUCTION = """\
You have a Python sandbox with matplotlib. WRITE AND RUN code NOW to create ONE
clean, minimal teaching chart that illuminates this concept — do not explain,
just build it.

Concept: {name}
Lesson title: {title}
Objective: {objective}

Use realistic illustrative values, clear axis labels, and a title. Set the size
with plt.figure(figsize=(6, 3.6)); save with
plt.savefig('/tmp/chart.png', dpi=130, bbox_inches='tight') — do NOT pass
figsize to savefig. Keep it uncluttered: a teaching aid, not a report.

Only if a chart genuinely cannot help this concept (purely ethical or
definitional, nothing quantitative or comparative to show) reply with exactly
NO_CHART and nothing else — but prefer to build a chart whenever one could aid
understanding.
"""


def chart_data_url(concept: ConceptNode, title: str, objective: str) -> str | None:
    """Return a base64 PNG data URL for a teaching chart, or None if unhelpful."""
    png = generate_chart_png(
        _INSTRUCTION.format(name=concept.name, title=title, objective=objective)
    )
    if not png:
        return None
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
