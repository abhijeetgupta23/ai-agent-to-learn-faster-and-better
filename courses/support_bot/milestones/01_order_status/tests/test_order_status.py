import pytest
import support_agent as agent


def test_tool_spec_has_a_description():
    tool = next(t for t in agent.TOOLS if t["name"] == "get_order_status")
    assert len(tool["description"].strip()) > 20
    assert "order_id" in tool["input_schema"]["properties"]


def test_lookup_returns_status_for_known_order():
    assert agent.get_order_status("1001") == "shipped"


def test_unknown_order_gives_a_clear_error():
    with pytest.raises(ValueError, match="9999"):
        agent.get_order_status("9999")
