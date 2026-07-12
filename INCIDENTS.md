# INCIDENTS.md — the documented incidents, primary-source-verified

The launch README motivates trifecta-lens with real, public incidents. A tool
whose entire moat is **not overclaiming** cannot cite them second-hand, so this
file is the verification record: every entry below was checked against its
**primary source** (the discovering researchers or the authoritative CVE record),
not against a news summary. Each was verified on **2026-07-13**.

The list is deliberately **small and A-tier**, not exhaustive. Two well-documented
incidents that clearly instantiate the lethal trifecta beat a long list of
half-verified ones — and adding an entry means verifying it here first, the same
discipline `CONTRIBUTING.md` asks of a catalog entry.

Each entry states, in its own words, **what trifecta-lens would and would not
see**. That honesty is the point: trifecta-lens detects *exposure and observed
flow*, it does not reproduce these exploits, and its v1 realized tier is
**verbatim-only** (`SPEC.md` §6, §8) — so a transformed/rendered exfiltration
channel is out of realized scope and we say so.

---

## The concept

**"The lethal trifecta for AI agents: private data, untrusted content, and
external communication"** — Simon Willison.
- **Reported:** 16 June 2025.
- **Primary source:** <https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/>
- **Verified:** 2026-07-13. Willison names the pattern and defines the three
  legs verbatim: (1) *access to your private data*, (2) *exposure to untrusted
  content*, and (3) *the ability to externally communicate* in a way that could
  exfiltrate that data. This is the coinage trifecta-lens is built around; it is
  a concept definition, **not** an incident.

---

## Documented incidents (primary-source-verified)

### EchoLeak — zero-click data exfiltration from Microsoft 365 Copilot (CVE-2025-32711)

- **Reported:** research disclosed by **Aim Labs** (since acquired by Cato
  Networks), 31 May 2025; **CVE-2025-32711** published by Microsoft on
  11 June 2025 (CVSS 9.3 per Microsoft; 7.5 per NVD).
- **Primary sources:**
  Aim Labs research — <https://www.catonetworks.com/blog/breaking-down-echoleak/> ·
  CVE record — <https://nvd.nist.gov/vuln/detail/CVE-2025-32711>
- **Verified:** 2026-07-13. The NVD description reads, verbatim: *"AI command
  injection in M365 Copilot allows an unauthorized attacker to disclose
  information over a network."*
- **What happened.** A single crafted email carried hidden instructions that
  slipped past Microsoft's prompt-injection classifier. When Copilot ingested the
  email, it followed the embedded directives, pulled the most sensitive data from
  the user's context, and exfiltrated it — **zero-click**, no user interaction.
  Aim Labs named the vulnerability class an *"LLM Scope Violation."*
- **The three legs.** Untrusted content = the attacker's email. Private data =
  the user's M365 context (chats, OneDrive, SharePoint, Teams). External
  communication = the exfiltration channel.
- **What trifecta-lens would and would not see.** From an inventory, the tool
  would report the **reachable/posture** trifecta — all three legs co-exposed in
  one agent context — which is precisely the exposure EchoLeak weaponized. It
  would **not** have produced a *realized* finding: the exfiltration rode a
  **rendered channel** (reference-style Markdown links and auto-fetched images via
  a Teams proxy), and v1 realized detection is verbatim-only — a transformed/
  rendered channel is explicitly out of scope (`SPEC.md` §8). EchoLeak is also not
  an MCP stack. It illustrates the *class*; trifecta-lens targets the same shape.

### GitHub MCP — private-repository exfiltration via a malicious issue

- **Reported:** **Invariant Labs** (Marco Milanta and Luca Beurer-Kellner),
  26 May 2025.
- **Primary source:** <https://invariantlabs.ai/blog/mcp-github-vulnerability>
- **Verified:** 2026-07-13. From the post: the agent *"goes through the list of
  issues until it finds the attack payload"* and *"willingly pulls private
  repository data into context,"* then *"leaks it into a pull request of the
  `pacman` repo, which is freely accessible to the attacker since it is public."*
  Demonstrated end-to-end even on Claude 4 Opus. Invariant frames it as an
  **architectural** issue, not a bug in the GitHub MCP server code.
- **The three legs.** Untrusted content = a malicious issue in a public repo.
  Private data = the user's private repositories, reachable with the same token.
  External communication = a pull request opened against a public repo.
- **What trifecta-lens would and would not see.** This is the closest public
  analogue to what trifecta-lens is built for: a **real MCP agent**, and an
  exfiltration channel — *writing content to a shared/public location* — that the
  default catalog already labels `sink:exfil` (`SPEC.md` §4). From an inventory,
  the tool would report the **reachable/posture** trifecta. And because the
  private data is written into the PR body **verbatim**, a trace that captured
  that flow would fire the **realized** tier — the one case in this file whose
  realized path is within v1 scope. We have **not** captured such a trace; the
  realized trifecta remains exercised only by a hand-authored fixture
  (`fixtures/worked_example.jsonl`, disclosed as such), which is exactly why the
  README does not claim a lethal trifecta observed in the wild.

---

## Scope caveat (read before citing these)

These incidents demonstrate the lethal-trifecta **class** in production systems.
trifecta-lens does not reproduce them and makes no claim to have observed them. It
reports, from a captured trace and inventory, where the same three legs are
**exposed** (reachable/posture) and where a verbatim sensitive value was
**observed** reaching a sink (realized). Two of the three legs in EchoLeak's
realized exfiltration used a transformed/rendered channel that v1 does not detect
— included here precisely so the limitation is stated alongside the motivation,
never buried.
