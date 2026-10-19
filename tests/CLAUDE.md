# Test conventions

- Mock every LLM call (monkeypatch `src.llm` or the tool's call site). pytest never hits the API.
- Tests must run offline with no `ANTHROPIC_API_KEY` set.
- Test the public interface (tools, agent, server endpoints), not private helpers.
- One test per acceptance criterion; name it after the criterion, e.g. `test_empty_answer_is_blocked`.
- Use `tmp_path` for any file state (memory store, spend ledger) — never write under `data/`.
