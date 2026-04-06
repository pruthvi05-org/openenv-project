"""
models.py — fully typed Pydantic-free data models for CodeReviewEnv.
Uses Python dataclasses + __post_init__ validation only (no external deps).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    ERROR    = "error"
    CRITICAL = "critical"

    def score(self) -> float:
        return {"info": 0.1, "warning": 0.3, "error": 0.7, "critical": 1.0}[self.value]


class ActionType(str, Enum):
    COMMENT         = "comment"
    REQUEST_CHANGES = "request_changes"
    APPROVE         = "approve"
    REJECT          = "reject"
    EXAMINE_FILE    = "examine_file"
    RUN_CHECK       = "run_check"


class Verdict(str, Enum):
    APPROVE          = "approve"
    REQUEST_CHANGES  = "request_changes"
    REJECT           = "reject"


class CIState(str, Enum):
    PASSING = "passing"
    FAILING = "failing"
    PENDING = "pending"
    SKIPPED = "skipped"


class IssueCategory(str, Enum):
    BUG             = "bug"
    SECURITY        = "security"
    STYLE           = "style"
    PERFORMANCE     = "performance"
    MISSING_TEST    = "missing_test"
    LOGIC_ERROR     = "logic_error"
    DEAD_CODE       = "dead_code"
    RACE_CONDITION  = "race_condition"


# ── File / diff models ────────────────────────────────────────────────────────

@dataclass
class DiffLine:
    line_no: int              # line number in new file (None if deletion)
    content: str
    change: str               # '+', '-', ' ' (context)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FileDiff:
    path: str
    language: str
    additions: int
    deletions: int
    lines: List[DiffLine] = field(default_factory=list)
    is_new_file: bool = False
    is_deleted: bool = False

    def __post_init__(self):
        if not self.path:
            raise ValueError("FileDiff.path cannot be empty")

    def get_line(self, line_no: int) -> Optional[DiffLine]:
        for dl in self.lines:
            if dl.line_no == line_no:
                return dl
        return None

    def added_lines(self) -> List[DiffLine]:
        return [dl for dl in self.lines if dl.change == "+"]

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d


# ── CI / test models ──────────────────────────────────────────────────────────

@dataclass
class CICheck:
    name: str
    state: CIState
    message: str = ""
    duration_s: float = 0.0

    def to_dict(self) -> Dict:
        return {**asdict(self), "state": self.state.value}


@dataclass
class CIStatus:
    overall: CIState
    checks: List[CICheck] = field(default_factory=list)
    run_url: str = ""

    def to_dict(self) -> Dict:
        return {
            "overall": self.overall.value,
            "checks": [c.to_dict() for c in self.checks],
            "run_url": self.run_url,
        }


@dataclass
class TestSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    coverage_pct: float = 0.0
    failed_test_names: List[str] = field(default_factory=list)

    def pass_rate(self) -> float:
        return self.passed / max(self.total, 1)

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Repository context ────────────────────────────────────────────────────────

@dataclass
class RepoContext:
    name: str
    language: str
    description: str = ""
    open_issues: int = 0
    stars: int = 0
    contributors: int = 0
    has_security_policy: bool = False
    coding_standards: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Ground-truth annotations (hidden from agent) ──────────────────────────────

@dataclass
class GroundTruthIssue:
    file_path: str
    line_no: int
    category: IssueCategory
    severity: Severity
    description: str
    suggested_fix: str = ""
    cvss_score: Optional[float] = None   # only for security issues

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "category": self.category.value,
            "severity": self.severity.value,
        }


@dataclass
class GroundTruth:
    issues: List[GroundTruthIssue] = field(default_factory=list)
    correct_verdict: Verdict = Verdict.REQUEST_CHANGES
    explanation: str = ""

    def issue_keys(self) -> List[tuple]:
        """Canonical (file, line, category) tuples for F1 computation."""
        return [(i.file_path, i.line_no, i.category.value) for i in self.issues]

    def to_dict(self) -> Dict:
        return {
            "issues": [i.to_dict() for i in self.issues],
            "correct_verdict": self.correct_verdict.value,
            "explanation": self.explanation,
        }


# ── Pull request ──────────────────────────────────────────────────────────────

@dataclass
class PullRequest:
    id: str
    title: str
    description: str
    author: str
    base_branch: str = "main"
    head_branch: str = "feature"
    files: List[FileDiff] = field(default_factory=list)
    ci_status: CIStatus = field(default_factory=lambda: CIStatus(CIState.PASSING))
    test_summary: TestSummary = field(default_factory=TestSummary)
    repo_context: RepoContext = field(
        default_factory=lambda: RepoContext(name="repo", language="python")
    )
    ground_truth: Optional[GroundTruth] = None   # not visible to agent

    def file_paths(self) -> List[str]:
        return [f.path for f in self.files]

    def get_file(self, path: str) -> Optional[FileDiff]:
        for f in self.files:
            if f.path == path:
                return f
        return None

    def to_obs_dict(self) -> Dict:
        """Returns observation dict — excludes ground_truth."""
        return {
            "pr_id": self.id,
            "pr_title": self.title,
            "pr_description": self.description,
            "author": self.author,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "files_changed": [f.to_dict() for f in self.files],
            "ci_status": self.ci_status.to_dict(),
            "test_summary": self.test_summary.to_dict(),
            "repo_context": self.repo_context.to_dict(),
        }


# ── Agent actions ─────────────────────────────────────────────────────────────

@dataclass
class AgentAction:
    action_type: ActionType
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    comment_body: Optional[str] = None
    severity: Optional[Severity] = None
    verdict: Optional[Verdict] = None
    reasoning: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.action_type, str):
            self.action_type = ActionType(self.action_type)
        if isinstance(self.severity, str) and self.severity:
            self.severity = Severity(self.severity)
        if isinstance(self.verdict, str) and self.verdict:
            self.verdict = Verdict(self.verdict)

    def is_terminal(self) -> bool:
        return self.action_type in (
            ActionType.APPROVE, ActionType.REJECT, ActionType.REQUEST_CHANGES
        )

    def validate(self) -> List[str]:
        errors = []
        if self.action_type == ActionType.COMMENT:
            if not self.file_path:
                errors.append("comment requires file_path")
            if not self.comment_body:
                errors.append("comment requires comment_body")
            if not self.severity:
                errors.append("comment requires severity")
        if self.action_type in (ActionType.APPROVE, ActionType.REQUEST_CHANGES, ActionType.REJECT):
            if not self.reasoning:
                errors.append(f"{self.action_type.value} requires reasoning")
        return errors

    def to_dict(self) -> Dict:
        return {
            "action_type": self.action_type.value,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "comment_body": self.comment_body,
            "severity": self.severity.value if self.severity else None,
            "verdict": self.verdict.value if self.verdict else None,
            "reasoning": self.reasoning,
        }


# ── Step result ────────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    obs: Dict[str, Any]
    reward: float
    terminated: bool
    truncated: bool
    info: Dict[str, Any] = field(default_factory=dict)

    def __iter__(self):
        return iter((self.obs, self.reward, self.terminated, self.truncated, self.info))

    def __repr__(self):
        return (
            f"StepResult(reward={self.reward:.4f}, terminated={self.terminated}, "
            f"truncated={self.truncated})"
        )
