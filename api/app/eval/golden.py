"""Golden dataset loading and validation.

Cases live in YAML next to this module so they can be reviewed as data rather
than buried in Python. Loading validates every field, because a typo in an
intent name or tool name would otherwise quietly depress the score and look
like a model regression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

GOLDEN_DIR = Path(__file__).parent / "golden"

VALID_INTENTS = {"schema", "crud", "analysis", "general"}

# Matching policy for the expected tool set.
#   subset — every expected tool must be selected; extras are allowed but
#            counted against precision. Right for most cases, where several
#            tool combinations are defensible.
#   exact  — the selected set must equal the expected set. Reserved for cases
#            where selecting anything extra is itself the error, e.g. a
#            greeting that should trigger no tools at all.
VALID_TOOLS_MODES = {"subset", "exact"}


@dataclass
class GoldenCase:
    id: str
    question: str
    expected_intent: str
    expected_tools: list[str] = field(default_factory=list)
    tools_mode: str = "subset"
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def validate(self, known_tools: set[str]) -> list[str]:
        """Return a list of problems; empty means the case is well-formed."""
        problems: list[str] = []
        if not self.id:
            problems.append("missing id")
        if not self.question.strip():
            problems.append(f"{self.id}: empty question")
        if self.expected_intent not in VALID_INTENTS:
            problems.append(
                f"{self.id}: unknown intent {self.expected_intent!r} "
                f"(valid: {sorted(VALID_INTENTS)})"
            )
        if self.tools_mode not in VALID_TOOLS_MODES:
            problems.append(f"{self.id}: unknown tools_mode {self.tools_mode!r}")
        for tool in self.expected_tools:
            if tool not in known_tools:
                problems.append(f"{self.id}: unknown tool {tool!r}")
        return problems


def load_cases(path: Path | None = None) -> list[GoldenCase]:
    """Load every golden case from `path` (a file or a directory)."""
    target = path or GOLDEN_DIR
    files = sorted(target.glob("*.yaml")) if target.is_dir() else [target]

    cases: list[GoldenCase] = []
    for file in files:
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        for raw in data.get("cases", []):
            cases.append(
                GoldenCase(
                    id=str(raw.get("id", "")),
                    question=str(raw.get("question", "")),
                    expected_intent=str(raw.get("expected_intent", "")),
                    expected_tools=list(raw.get("expected_tools") or []),
                    tools_mode=str(raw.get("tools_mode", "subset")),
                    tags=list(raw.get("tags") or []),
                    notes=str(raw.get("notes", "")),
                )
            )
    return cases


def validate_cases(cases: list[GoldenCase], known_tools: set[str]) -> list[str]:
    """Validate a whole dataset, including duplicate ids."""
    problems: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            problems.append(f"duplicate id {case.id!r}")
        seen.add(case.id)
        problems.extend(case.validate(known_tools))
    return problems
