"""
graders.py — agent graders for each task difficulty.

Reward breakdown (all graders return float in [0.0, 1.0]):

  EasyGrader    (single bug)
    0.50  bug_found        — agent commented on the exact bug line(s)
    0.25  severity_match   — correct severity label
    0.25  verdict_match    — correct final verdict

  MediumGrader  (multi-issue PR)
    0.35  bug_f1           — F1 over (file, line, category) issue tuples
    0.20  comment_quality  — keyword overlap with gold descriptions
    0.20  severity_macro   — per-issue severity accuracy (macro avg)
    0.15  verdict_match    — correct final verdict
    0.10  efficiency       — step penalty (fewer steps → higher bonus)

  HardGrader    (security audit)
    0.40  issue_recall     — recall over security issues (finding all matters)
    0.20  cvss_accuracy    — CVSS tier accuracy (low/med/high/crit)
    0.20  mitigation_qual  — keyword overlap with gold suggested_fix
    0.15  verdict_match    — correct verdict
    0.05  false_pos_pen    — penalty for flagging clean code as issues
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from openenv.models import (
    AgentAction, ActionType, GroundTruth, GroundTruthIssue,
    IssueCategory, PullRequest, Severity, Verdict,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared utilities
# ─────────────────────────────────────────────────────────────────────────────

def _tokens(text: str) -> set:
    """Bag of lowercase word tokens, strips punctuation."""
    return set(re.findall(r"[a-z0-9_]+", (text or "").lower()))


def _keyword_overlap(candidate: str, reference: str) -> float:
    """Jaccard similarity over token bags."""
    c, r = _tokens(candidate), _tokens(reference)
    if not r:
        return 0.0
    return len(c & r) / len(c | r)


def _severity_tier(s: Severity) -> int:
    return {"info": 0, "warning": 1, "error": 2, "critical": 3}[s.value]


def _cvss_tier(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    if score < 4.0:
        return "low"
    if score < 7.0:
        return "medium"
    if score < 9.0:
        return "high"
    return "critical"


def _agent_verdict(actions: List[AgentAction]) -> Optional[Verdict]:
    for a in reversed(actions):
        if a.action_type in (ActionType.APPROVE, ActionType.REQUEST_CHANGES, ActionType.REJECT):
            return a.verdict or Verdict(a.action_type.value.replace("_", "_"))
    return None


def _normalise_verdict(action: AgentAction) -> Optional[Verdict]:
    if action.action_type == ActionType.APPROVE:
        return Verdict.APPROVE
    if action.action_type == ActionType.REJECT:
        return Verdict.REJECT
    if action.action_type == ActionType.REQUEST_CHANGES:
        return Verdict.REQUEST_CHANGES
    if action.verdict:
        return action.verdict
    return None


def _agent_comments(actions: List[AgentAction]) -> List[AgentAction]:
    return [a for a in actions if a.action_type == ActionType.COMMENT]


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GradeResult:
    total_reward: float
    breakdown: Dict[str, float] = field(default_factory=dict)
    feedback: List[str] = field(default_factory=list)

    def __repr__(self):
        parts = ", ".join(f"{k}={v:.3f}" for k, v in self.breakdown.items())
        return f"GradeResult(total={self.total_reward:.4f}, [{parts}])"


# ─────────────────────────────────────────────────────────────────────────────
# Easy grader
# ─────────────────────────────────────────────────────────────────────────────

class EasyGrader:
    """
    Rewards:
      bug_found (0.50)     — agent placed a comment within ±2 lines of any gold bug
      severity_match (0.25) — severity label within 1 tier of gold
      verdict_match (0.25) — exact verdict match
    """

    WEIGHTS = {"bug_found": 0.50, "severity_match": 0.25, "verdict_match": 0.25}

    def grade(self, pr: PullRequest, actions: List[AgentAction], n_steps: int) -> GradeResult:
        gt = pr.ground_truth
        comments = _agent_comments(actions)
        feedback = []

        # ── bug_found ──────────────────────────────────────────────────────
        bugs_hit = 0
        for issue in gt.issues:
            hit = any(
                a.file_path == issue.file_path
                and a.line_number is not None
                and abs(a.line_number - issue.line_no) <= 2
                for a in comments
            )
            if hit:
                bugs_hit += 1
            else:
                feedback.append(f"Missed bug at {issue.file_path}:{issue.line_no}")
        bug_score = bugs_hit / max(len(gt.issues), 1)

        # ── severity_match ─────────────────────────────────────────────────
        sev_scores = []
        for issue in gt.issues:
            gold_tier = _severity_tier(issue.severity)
            agent_sev = next(
                (a.severity for a in comments
                 if a.file_path == issue.file_path
                 and a.line_number is not None
                 and abs(a.line_number - issue.line_no) <= 2
                 and a.severity is not None),
                None
            )
            if agent_sev is None:
                sev_scores.append(0.0)
            else:
                diff = abs(_severity_tier(agent_sev) - gold_tier)
                sev_scores.append(1.0 if diff == 0 else 0.5 if diff == 1 else 0.0)
        sev_score = sum(sev_scores) / max(len(sev_scores), 1)

        # ── verdict_match ──────────────────────────────────────────────────
        final_verdict = None
        for a in reversed(actions):
            v = _normalise_verdict(a)
            if v:
                final_verdict = v
                break
        verdict_score = 1.0 if final_verdict == gt.correct_verdict else 0.0
        if verdict_score == 0.0:
            feedback.append(f"Wrong verdict: got {final_verdict}, expected {gt.correct_verdict.value}")

        breakdown = {
            "bug_found":      round(bug_score, 4),
            "severity_match": round(sev_score, 4),
            "verdict_match":  round(verdict_score, 4),
        }
        total = sum(breakdown[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        return GradeResult(total_reward=round(total, 4), breakdown=breakdown, feedback=feedback)


# ─────────────────────────────────────────────────────────────────────────────
# Medium grader
# ─────────────────────────────────────────────────────────────────────────────

class MediumGrader:
    """
    Rewards:
      bug_f1 (0.35)          — F1 over (file, ~line, category) tuples
      comment_quality (0.20) — avg Jaccard similarity to gold descriptions
      severity_macro (0.20)  — per-issue severity tier accuracy
      verdict_match (0.15)   — correct verdict
      efficiency (0.10)      — bonus for resolving in ≤ half max_steps
    """

    WEIGHTS = {
        "bug_f1": 0.35,
        "comment_quality": 0.20,
        "severity_macro": 0.20,
        "verdict_match": 0.15,
        "efficiency": 0.10,
    }
    MAX_STEPS = 25

    def grade(self, pr: PullRequest, actions: List[AgentAction], n_steps: int) -> GradeResult:
        gt = pr.ground_truth
        comments = _agent_comments(actions)
        feedback = []

        # ── Match comments to gold issues ──────────────────────────────────
        matched_gold = set()
        matched_agent = set()
        quality_scores = []
        sev_scores = []

        for gi, issue in enumerate(gt.issues):
            best_qual = 0.0
            best_match_ai = None
            for ai, a in enumerate(comments):
                if a.file_path != issue.file_path:
                    continue
                line_close = (a.line_number is None or abs(a.line_number - issue.line_no) <= 3)
                if not line_close:
                    continue
                qual = _keyword_overlap(a.comment_body or "", issue.description)
                if qual > best_qual:
                    best_qual = qual
                    best_match_ai = ai

            if best_qual > 0.1:  # threshold to count as a match
                matched_gold.add(gi)
                if best_match_ai is not None:
                    matched_agent.add(best_match_ai)
                quality_scores.append(best_qual)
                # severity
                agent_sev = comments[best_match_ai].severity if best_match_ai is not None else None
                if agent_sev:
                    diff = abs(_severity_tier(agent_sev) - _severity_tier(issue.severity))
                    sev_scores.append(1.0 if diff == 0 else 0.5 if diff == 1 else 0.0)
                else:
                    sev_scores.append(0.0)
            else:
                feedback.append(f"Missed issue at {issue.file_path}:{issue.line_no} ({issue.category.value})")

        # F1
        tp = len(matched_gold)
        fp = len(comments) - len(matched_agent)
        fn = len(gt.issues) - tp
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)

        # Comment quality
        qual_score = sum(quality_scores) / max(len(gt.issues), 1)

        # Severity
        sev_score = sum(sev_scores) / max(len(gt.issues), 1)

        # Verdict
        final_verdict = None
        for a in reversed(actions):
            v = _normalise_verdict(a)
            if v:
                final_verdict = v
                break
        verdict_score = 1.0 if final_verdict == gt.correct_verdict else 0.0

        # Efficiency
        efficiency = max(0.0, 1.0 - (n_steps / self.MAX_STEPS))

        breakdown = {
            "bug_f1":          round(f1, 4),
            "comment_quality": round(qual_score, 4),
            "severity_macro":  round(sev_score, 4),
            "verdict_match":   round(verdict_score, 4),
            "efficiency":      round(efficiency, 4),
        }
        total = sum(breakdown[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        return GradeResult(total_reward=round(total, 4), breakdown=breakdown, feedback=feedback)


# ─────────────────────────────────────────────────────────────────────────────
# Hard grader
# ─────────────────────────────────────────────────────────────────────────────

class HardGrader:
    """
    Rewards:
      issue_recall (0.40)    — recall over security issues (missing one is costly)
      cvss_accuracy (0.20)   — CVSS tier accuracy per security issue
      mitigation_qual (0.20) — keyword overlap with gold suggested_fix
      verdict_match (0.15)   — correct verdict
      false_pos_pen (0.05)   — penalty deducted for flagging non-issues as critical
    """

    WEIGHTS = {
        "issue_recall":    0.40,
        "cvss_accuracy":   0.20,
        "mitigation_qual": 0.20,
        "verdict_match":   0.15,
        "false_pos_pen":   0.05,
    }
    MAX_STEPS = 40

    def grade(self, pr: PullRequest, actions: List[AgentAction], n_steps: int) -> GradeResult:
        gt = pr.ground_truth
        comments = _agent_comments(actions)
        security_issues = [i for i in gt.issues if i.category == IssueCategory.SECURITY]
        feedback = []

        # ── Issue recall (security-only) ───────────────────────────────────
        found = 0
        cvss_scores = []
        mitig_scores = []

        for issue in security_issues:
            best_qual = 0.0
            best_comment = None
            for a in comments:
                if a.file_path and a.file_path != issue.file_path:
                    continue
                line_close = (a.line_number is None or abs(a.line_number - issue.line_no) <= 4)
                qual = _keyword_overlap(a.comment_body or "", issue.description)
                if qual > best_qual and line_close:
                    best_qual = qual
                    best_comment = a

            if best_qual > 0.08:
                found += 1
                # CVSS tier
                gold_tier = _cvss_tier(issue.cvss_score)
                if best_comment and best_comment.severity:
                    agent_tier_map = {
                        Severity.INFO: "low", Severity.WARNING: "medium",
                        Severity.ERROR: "high", Severity.CRITICAL: "critical",
                    }
                    agent_tier = agent_tier_map.get(best_comment.severity, "unknown")
                    cvss_scores.append(1.0 if agent_tier == gold_tier else 0.5 if abs(
                        ["low","medium","high","critical"].index(agent_tier) -
                        ["low","medium","high","critical"].index(gold_tier)
                    ) == 1 else 0.0)
                else:
                    cvss_scores.append(0.0)
                # Mitigation quality
                mitig_scores.append(
                    _keyword_overlap(best_comment.comment_body or "", issue.suggested_fix)
                    if best_comment else 0.0
                )
            else:
                feedback.append(f"Missed security issue at {issue.file_path}:{issue.line_no}")

        recall = found / max(len(security_issues), 1)
        cvss_score = sum(cvss_scores) / max(len(security_issues), 1)
        mitig_score = sum(mitig_scores) / max(len(security_issues), 1)

        # ── Verdict ────────────────────────────────────────────────────────
        final_verdict = None
        for a in reversed(actions):
            v = _normalise_verdict(a)
            if v:
                final_verdict = v
                break
        verdict_score = 1.0 if final_verdict == gt.correct_verdict else 0.0

        # ── False positive penalty (flagging clean code as CRITICAL) ───────
        false_crits = sum(
            1 for a in comments
            if a.severity == Severity.CRITICAL
            and not any(
                a.file_path == i.file_path
                and a.line_number is not None
                and abs(a.line_number - i.line_no) <= 4
                for i in gt.issues
            )
        )
        # For the clean PR (hard-003), gt.issues is empty — all criticals are false positives
        fp_penalty = min(1.0, false_crits * 0.2)
        fp_score = max(0.0, 1.0 - fp_penalty)

        breakdown = {
            "issue_recall":    round(recall, 4),
            "cvss_accuracy":   round(cvss_score, 4),
            "mitigation_qual": round(mitig_score, 4),
            "verdict_match":   round(verdict_score, 4),
            "false_pos_pen":   round(fp_score, 4),
        }
        total = sum(breakdown[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        return GradeResult(total_reward=round(total, 4), breakdown=breakdown, feedback=feedback)


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_grader(difficulty: str):
    return {"easy": EasyGrader, "medium": MediumGrader, "hard": HardGrader}[difficulty]()
