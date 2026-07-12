"""Extraction parameters — fixed, and disclosed (SPEC.md §6.1, DECISIONS.md D4).

These are the knobs that bound **what the realized tier is able to see**. They
are deliberately *not* user-tunable: the catalog stays the only tunable layer
(`CLAUDE.md` invariant 2, `DESIGN.md` §4), so "the automaton is fixed; tunability
only via the catalog" remains literally true.

But they **must be disclosed**. An undisclosed threshold silently bounds the
search, which makes "no finding" un-auditable — the same honesty failure as an
overclaim, pointed the other way. Every finding therefore carries these values in
its ``detected_under`` field, and the report states them even when it has nothing
to report.

``ExtractionConfig`` is parameterizable only so the *test suite* can sweep the
threshold and measure the false-positive rate the constant is justified by
(`tests/test_extraction_config.py`). Production code uses ``EXTRACTION``.
"""

from dataclasses import dataclass, field
from typing import Any, Final

#: The match rule (SPEC.md §6): the value must OCCUR in the sink's payload,
#: untransformed. "Verbatim" constrains the value, never the surrounding body.
MATCH_CONTAINMENT: Final[str] = "containment"

_NORMALIZATION: Final[tuple[str, ...]] = ("trim", "casefold", "collapse-whitespace")


@dataclass(frozen=True)
class ExtractionConfig:
    """The declared bounds on taint extraction and matching."""

    #: Values shorter than this are not tracked: a short string collides with
    #: ordinary payload text and yields noise, not evidence. The v1 value of 8 is
    #: justified by a MEASURED false-positive rate over the benign corpus, not by
    #: assertion (SPEC.md §6.1).
    min_value_chars: int = 8
    match: str = MATCH_CONTAINMENT
    normalization: tuple[str, ...] = field(default=_NORMALIZATION)

    def to_dict(self) -> dict[str, Any]:
        """The ``detected_under`` payload carried by every finding."""
        return {
            "match": self.match,
            "min_value_chars": self.min_value_chars,
            "normalization": list(self.normalization),
        }

    def describe(self) -> str:
        """One line for the human report — including a silent one."""
        return (
            f"match={self.match}, min_value_chars={self.min_value_chars}, "
            f"normalization={'|'.join(self.normalization)}"
        )


#: The shipped configuration. Fixed.
EXTRACTION: Final[ExtractionConfig] = ExtractionConfig()
