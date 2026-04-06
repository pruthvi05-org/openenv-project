"""
env.py — CodeReviewEnv: the main OpenEnv-compatible environment.

A real-world software engineering environment where an AI agent
acts as a senior code reviewer on GitHub-style pull requests.

API:
    env = CodeReviewEnv(difficulty="medium", seed=42)
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(action)
    state_dict = env.state()
    env.render()

Actions are AgentAction dataclass instances.
Observations are Python dicts matching the PR observation schema.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from openenv.models import (
    AgentAction, ActionType, PullRequest, Severity, StepResult, Verdict,
)
from openenv.dataset import get_pr, ALL_PRS
from openenv.graders import get_grader, GradeResult


# ─────────────────────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────────────────────

MAX_STEPS = {"easy": 10, "medium": 25, "hard": 40}
N_PRS     = {k: len(v) for k, v in ALL_PRS.items()}


class CodeReviewEnv:
    """
    CodeReview OpenEnv Environment.

    Parameters
    ----------
    difficulty  : "easy" | "medium" | "hard"
    pr_index    : fixed PR index (None = rotate through all PRs)
    seed        : RNG seed for reproducibility
    """

    metadata = {
        "name": "CodeReviewEnv-v1",
        "version": "1.0.0",
        "domain": "software_engineering",
        "real_world": True,
        "spec": "openenv.yaml",
    }

    def __init__(
        self,
        difficulty: str = "easy",
        pr_index: Optional[int] = None,
        seed: int = 42,
    ):
        if difficulty not in MAX_STEPS:
            raise ValueError(f"difficulty must be one of {list(MAX_STEPS)}, got {difficulty!r}")
        self.difficulty = difficulty
        self.pr_index = pr_index
        self.seed = seed
        self._rng = random.Random(seed)
        self._max_steps = MAX_STEPS[difficulty]

        # Episode state (initialised by reset())
        self._pr: Optional[PullRequest] = None
        self._actions: List[AgentAction] = []
        self._step_count: int = 0
        self._episode_count: int = 0
        self._total_reward: float = 0.0
        self._intermediate_rewards: List[float] = []
        self._examined_files: set = set()
        self._checks_run: List[str] = []
        self._start_time: float = 0.0
        self._last_grade: Optional[GradeResult] = None
        self._grader = get_grader(difficulty)

        # PR rotation
        self._pr_queue: List[int] = []

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self, seed: Optional[int] = None) -> Tuple[Dict, Dict]:
        if seed is not None:
            self.seed = seed
            self._rng = random.Random(seed)

        self._episode_count += 1
        self._step_count = 0
        self._total_reward = 0.0
        self._actions = []
        self._intermediate_rewards = []
        self._examined_files = set()
        self._checks_run = []
        self._start_time = time.perf_counter()
        self._last_grade = None

        # Select PR
        if self.pr_index is not None:
            idx = self.pr_index
        else:
            if not self._pr_queue:
                n = N_PRS[self.difficulty]
                self._pr_queue = self._rng.sample(range(n), n)
            idx = self._pr_queue.pop()

        self._pr = get_pr(self.difficulty, idx)

        obs = self._observe()
        info = {
            "episode": self._episode_count,
            "difficulty": self.difficulty,
            "pr_id": self._pr.id,
            "max_steps": self._max_steps,
        }
        return obs, info

    # ── Step ──────────────────────────────────────────────────────────────────

    def step(self, action: AgentAction) -> StepResult:
        if self._pr is None:
            raise RuntimeError("Call reset() before step()")
        if not isinstance(action, AgentAction):
            raise TypeError(f"action must be AgentAction, got {type(action)}")

        # Validate action
        errors = action.validate()
        if errors:
            obs = self._observe()
            return StepResult(
                obs=obs, reward=-0.05, terminated=False, truncated=False,
                info={"validation_errors": errors, "step": self._step_count},
            )

        self._actions.append(action)
        self._step_count += 1

        # Immediate rewards for non-terminal actions
        intermediate_reward = self._immediate_reward(action)
        self._intermediate_rewards.append(intermediate_reward)

        # Terminal actions trigger grading
        terminated = action.is_terminal()
        truncated = not terminated and self._step_count >= self._max_steps

        if terminated or truncated:
            grade = self._grader.grade(self._pr, self._actions, self._step_count)
            self._last_grade = grade
            final_reward = grade.total_reward
            self._total_reward += final_reward
            info = {
                "step": self._step_count,
                "total_reward": round(self._total_reward, 4),
                "grade": {
                    "total": grade.total_reward,
                    "breakdown": grade.breakdown,
                    "feedback": grade.feedback,
                },
                "pr_id": self._pr.id,
                "elapsed_s": round(time.perf_counter() - self._start_time, 3),
            }
            return StepResult(
                obs=self._observe(),
                reward=final_reward,
                terminated=terminated,
                truncated=truncated,
                info=info,
            )
        else:
            self._total_reward += intermediate_reward
            obs = self._observe()
            return StepResult(
                obs=obs,
                reward=intermediate_reward,
                terminated=False,
                truncated=False,
                info={
                    "step": self._step_count,
                    "total_reward": round(self._total_reward, 4),
                    "action": action.action_type.value,
                    "examined_files": list(self._examined_files),
                },
            )

    # ── State ─────────────────────────────────────────────────────────────────

    def state(self) -> Dict[str, Any]:
        if self._pr is None:
            return {"status": "not_started", "difficulty": self.difficulty}
        gt = self._pr.ground_truth
        return {
            "env": "CodeReviewEnv-v1",
            "difficulty": self.difficulty,
            "episode": self._episode_count,
            "step": self._step_count,
            "max_steps": self._max_steps,
            "pr_id": self._pr.id,
            "pr_title": self._pr.title,
            "n_files": len(self._pr.files),
            "n_actions": len(self._actions),
            "n_comments": sum(1 for a in self._actions if a.action_type == ActionType.COMMENT),
            "examined_files": sorted(self._examined_files),
            "checks_run": self._checks_run,
            "total_reward": round(self._total_reward, 4),
            "intermediate_rewards": self._intermediate_rewards,
            "last_grade": (
                {
                    "total": self._last_grade.total_reward,
                    "breakdown": self._last_grade.breakdown,
                }
                if self._last_grade else None
            ),
            "ci_state": self._pr.ci_status.overall.value,
            "test_pass_rate": round(self._pr.test_summary.pass_rate(), 3),
            "n_gold_issues": len(gt.issues) if gt else "?",
            "gold_verdict": gt.correct_verdict.value if gt else "?",
        }

    # ── Render ────────────────────────────────────────────────────────────────

    def render(self) -> str:
        if self._pr is None:
            return "CodeReviewEnv (not started — call reset())"
        pr = self._pr
        lines = [
            f"╔══════════════════════════════════════════════════╗",
            f"║  CodeReviewEnv  [{self.difficulty.upper():^6}]  "
            f"step {self._step_count}/{self._max_steps}          ║",
            f"╚══════════════════════════════════════════════════╝",
            f"  PR #{pr.id}  ·  {pr.title}",
            f"  Author: {pr.author}   {pr.base_branch} ← {pr.head_branch}",
            f"  Files : {len(pr.files)} changed   "
            f"CI: {pr.ci_status.overall.value.upper()}   "
            f"Tests: {pr.test_summary.passed}/{pr.test_summary.total}  "
            f"({pr.test_summary.coverage_pct:.0f}% cov)",
            "",
            f"  Files changed:",
        ]
        for f in pr.files:
            examined = "✓" if f.path in self._examined_files else " "
            lines.append(f"    [{examined}] {f.path}  (+{f.additions}/-{f.deletions})  [{f.language}]")

        lines += [
            "",
            f"  Agent actions ({len(self._actions)}):",
        ]
        for a in self._actions[-5:]:   # last 5
            icon = {"comment": "💬", "examine_file": "🔍", "run_check": "🔬",
                    "approve": "✅", "reject": "❌", "request_changes": "🔄"}.get(
                a.action_type.value, "•"
            )
            extra = ""
            if a.action_type == ActionType.COMMENT:
                extra = f" @ {a.file_path}:{a.line_number} [{a.severity.value if a.severity else '?'}]"
            elif a.action_type in (ActionType.APPROVE, ActionType.REJECT, ActionType.REQUEST_CHANGES):
                extra = f" — {(a.reasoning or '')[:60]}"
            lines.append(f"    {icon} {a.action_type.value}{extra}")

        if self._last_grade:
            lines += [
                "",
                f"  ── Grade ──────────────────────────────────────────",
                f"  Total reward: {self._last_grade.total_reward:.4f}",
            ]
            for k, v in self._last_grade.breakdown.items():
                bar = "█" * int(v * 20) + "░" * (20 - int(v * 20))
                lines.append(f"    {k:<20} [{bar}] {v:.3f}")
        return "\n".join(lines)

    # ── Observation ────────────────────────────────────────────────────────────

    def _observe(self) -> Dict[str, Any]:
        obs = self._pr.to_obs_dict()
        obs["step_history"] = [a.to_dict() for a in self._actions]
        obs["examined_files"] = sorted(self._examined_files)
        obs["checks_run"] = self._checks_run
        obs["steps_remaining"] = self._max_steps - self._step_count
        return obs

    # ── Immediate reward shaping ───────────────────────────────────────────────

    def _immediate_reward(self, action: AgentAction) -> float:
        """
        Small shaped rewards for useful non-terminal actions.
        Encourages the agent to examine files and run checks before commenting.
        All values are small to not dominate the terminal grade reward.
        """
        if action.action_type == ActionType.EXAMINE_FILE:
            if action.file_path and action.file_path in self._pr.file_paths():
                if action.file_path not in self._examined_files:
                    self._examined_files.add(action.file_path)
                    return 0.02  # reward first examination of each file
            return 0.0

        if action.action_type == ActionType.RUN_CHECK:
            check_name = action.comment_body or "generic"
            if check_name not in self._checks_run:
                self._checks_run.append(check_name)
                return 0.01  # reward running unique checks
            return 0.0

        if action.action_type == ActionType.COMMENT:
            # Small reward for commenting on examined files
            if action.file_path in self._examined_files:
                return 0.005
            # Tiny penalty for commenting on unexamined files (impulsive)
            return -0.005

        # Penalty for redundant actions
        if action.action_type in (ActionType.EXAMINE_FILE,) and action.file_path in self._examined_files:
            return -0.01

        return 0.0

    # ── Convenience ───────────────────────────────────────────────────────────

    def current_pr(self) -> Optional[PullRequest]:
        return self._pr

    def action_space_sample(self) -> AgentAction:
        """Sample a random valid action (for random baseline agents)."""
        action_types = list(ActionType)
        at = self._rng.choice(action_types)
        files = self._pr.file_paths() if self._pr else []
        file = self._rng.choice(files) if files else None
        return AgentAction(
            action_type=at,
            file_path=file,
            line_number=self._rng.randint(1, 30) if file else None,
            comment_body="Reviewed this section." if at == ActionType.COMMENT else None,
            severity=self._rng.choice(list(Severity)) if at == ActionType.COMMENT else None,
            verdict=(Verdict.REQUEST_CHANGES if at == ActionType.REQUEST_CHANGES
                     else Verdict.APPROVE if at == ActionType.APPROVE
                     else Verdict.REJECT if at == ActionType.REJECT
                     else None),
            reasoning="Auto-sampled reasoning." if at in (
                ActionType.APPROVE, ActionType.REJECT, ActionType.REQUEST_CHANGES
            ) else None,
        )
