import inspect
import re

import pytest
import support_agent as agent


def test_refund_within_policy_succeeds():
    assert agent.issue_refund("1001", 10.0)["refunded"] == 10.0


def test_refund_over_order_total_is_refused():
    with pytest.raises(ValueError, match="over"):
        agent.issue_refund("1002", 999)


def test_refund_already_refunded_is_refused():
    with pytest.raises(ValueError, match="already"):
        agent.issue_refund("1003", 5)


def test_both_tools_are_described():
    names = {t["name"]: t for t in agent.TOOLS}
    assert {"get_order_status", "issue_refund"} <= set(names)
    for t in names.values():
        assert len(t["description"].strip()) > 20


def test_tools_are_not_keyword_routed():
    source = inspect.getsource(agent)
    assert not re.search(r"""if\s+["']\w+["']\s+in\s+\w+""", source)
