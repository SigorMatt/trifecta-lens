"""demo/tools.py — the three stub tools of the vulnerable demo agent.

Each tool is deliberately ordinary:

* ``fetch``   returns the contents of a web page (an *untrusted source*).
* ``vault``   reads a stored secret from ``secret.txt`` (*sensitive data*).
* ``webhook`` POSTs a body outbound and logs it (the *exfil sink*).

None of them is rigged to leak. The page ``fetch`` returns happens to carry an
indirect prompt-injection instruction in its body; whether that instruction is
acted on is up to the model, not this code. That is the whole point (CLAUDE.md:
grateful realism, not a strawman).

Network and file I/O are allowed here — ``demo/`` lives OUTSIDE the analyzer
core (``trifecta_lens/``), which never touches the network (CLAUDE.md
invariant 1). These functions are pure enough to unit-test directly: ``fetch``
and ``vault`` read committed data files; ``webhook`` records its body into an
injectable :class:`Outbox` and sends via an injectable ``sender`` (defaulting to
a real POST, swapped for a no-network stub in tests).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
POISONED_PAGE_PATH = DEMO_DIR / "poisoned.html"
SECRET_PATH = DEMO_DIR / "secret.txt"


def fetch(url: str, *, page_path: Path = POISONED_PAGE_PATH) -> str:
    """Return the page content for ``url``.

    The demo serves a single page. It reads like an ordinary release-notes
    document but hides an instruction in its markup — structurally the same
    move as a poisoned GitHub issue, GitLab project file, or shared document
    in the documented incidents (see README.md). The content is *data*: this
    function neither inspects nor acts on it.
    """
    del url  # one-page demo; the URL is recorded in the span, not branched on
    return page_path.read_text(encoding="utf-8")


def vault(path: str = "secret.txt", *, secret_path: Path = SECRET_PATH) -> str:
    """Read and return the stored secret. An ordinary secret-reader tool."""
    del path  # one-secret demo; the requested path is recorded, not branched on
    return secret_path.read_text(encoding="utf-8").strip()


class Outbox:
    """Records what the webhook sink was asked to send.

    The ``RECEIVED <body>`` line is the "logs it" half of the sink and the
    demo's shareable moment (ROADMAP Phase 1). Keeping it a plain in-memory
    list makes the sink trivially testable without a network listener.
    """

    def __init__(self) -> None:
        self.received: list[str] = []

    def record(self, body: str) -> str:
        line = f"RECEIVED {body}"
        self.received.append(line)
        return line


#: A sink transport: given a URL and a body, attempt delivery and return a
#: short human status. Injectable so tests can run without the network.
Sender = Callable[[str, str], str]


def _urllib_post(url: str, body: str) -> str:
    """Real outbound POST. Network is allowed in ``demo/`` (never in core).

    A missing local listener must not abort the demo: the body has already
    been logged by the :class:`Outbox`, which is the observation the recorded
    trace captures. Delivery failures are reported, not raised.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return f"delivered ({response.status})"
    except (urllib.error.URLError, OSError) as exc:
        return f"unsent ({exc.__class__.__name__})"


def webhook(
    url: str,
    body: str,
    *,
    outbox: Outbox,
    sender: Sender = _urllib_post,
) -> str:
    """Outbound sink: log the body, then POST it. Returns a status string."""
    logged = outbox.record(body)
    status = sender(url, body)
    return f"{logged}; delivery={status}"


# --- Issue-triage tools -----------------------------------------------------
#
# The triage task the demo agent is actually given: list the open issues, read
# each one, and comment a short summary. These read from a directory of markdown
# issue files (an *untrusted source*, structurally like the fetched page): the
# body of one issue happens to carry an indirect prompt-injection instruction.
# Whether the model acts on it is up to the model, not this code.


def _issue_path(issue_id: str, issues_dir: Path) -> Path:
    return issues_dir / f"{issue_id}.md"


def list_issues(*, issues_dir: Path) -> list[dict[str, str]]:
    """List the open issues as ``{"id", "title"}`` records.

    ``id`` is the filename stem (e.g. ``issue-2``); ``title`` is taken from the
    file's leading ``Title:`` line. Directory order is sorted for determinism.
    """
    records: list[dict[str, str]] = []
    for path in sorted(issues_dir.glob("*.md")):
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        title = first_line.removeprefix("Title:").strip()
        records.append({"id": path.stem, "title": title})
    return records


def read_issue(issue_id: str, *, issues_dir: Path) -> str:
    """Return the full text of one issue. The content is *data*: not acted on."""
    return _issue_path(issue_id, issues_dir).read_text(encoding="utf-8")


class CommentStore:
    """Records the triage comments the agent posts. Mirrors :class:`Outbox`.

    A plain in-memory list keeps ``post_comment`` trivially testable without a
    real issue tracker — the demo never mutates an external system.
    """

    def __init__(self) -> None:
        self.comments: list[str] = []

    def record(self, issue_id: str, body: str) -> str:
        line = f"COMMENT {issue_id} {body}"
        self.comments.append(line)
        return line


def post_comment(issue_id: str, body: str, *, comments: CommentStore) -> str:
    """Record a triage comment into ``comments`` and return a confirmation."""
    comments.record(issue_id, body)
    return f"comment posted on {issue_id}"
