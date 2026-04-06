#!/usr/bin/env python3
"""
tests/test_env.py — smoke tests and grader unit tests.

Run: python tests/test_env.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from openenv import CodeReviewEnv, AgentAction, ActionType, Severity, Verdict
from openenv.graders import EasyGrader, MediumGrader, HardGrader
from openenv.dataset import get_pr

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
errors = []

def check(name, cond, msg=""):
    if cond:
        print(f"  {PASS} {name}")
    else:
        print(f"  {FAIL} {name}  {msg}")
        errors.append(name)

# ──────────────────────────────────────────────
# 1. Environment API
# ──────────────────────────────────────────────
print("\n[1] Environment API")

env = CodeReviewEnv(difficulty="easy", seed=42)
check("state() before reset", "not_started" in env.state()["status"])

obs, info = env.reset(seed=42)
check("reset() returns dict obs", isinstance(obs, dict))
check("reset() info has episode", "episode" in info)
check("obs has pr_title", "pr_title" in obs)
check("obs has files_changed", "files_changed" in obs and len(obs["files_changed"]) > 0)
check("obs no ground_truth leak", "ground_truth" not in obs)
check("state() has pr_id", "pr_id" in env.state())

# Bad action rejected
bad = AgentAction(action_type=ActionType.COMMENT, file_path=None, comment_body=None)
result = env.step(bad)
check("invalid action returns negative reward", result.reward < 0)

# Examine file
pr = env.current_pr()
act = AgentAction(action_type=ActionType.EXAMINE_FILE, file_path=pr.files[0].path)
r2 = env.step(act)
check("examine_file gives positive reward", r2.reward > 0)
check("not terminated after examine", not r2.terminated)
check("examined_files tracked", pr.files[0].path in env.state()["examined_files"])

# Terminal action
term = AgentAction(
    action_type=ActionType.REQUEST_CHANGES,
    verdict=Verdict.REQUEST_CHANGES,
    reasoning="Found issues.",
)
r3 = env.step(term)
check("terminal action terminates", r3.terminated)
check("grade in info", "grade" in r3.info)
check("reward in [0,1]", 0.0 <= r3.reward <= 1.0, f"got {r3.reward}")

# ──────────────────────────────────────────────
# 2. Reset reproducibility
# ──────────────────────────────────────────────
print("\n[2] Reproducibility")

env2a = CodeReviewEnv(difficulty="easy", seed=99)
obs_a, _ = env2a.reset(seed=99)
env2b = CodeReviewEnv(difficulty="easy", seed=99)
obs_b, _ = env2b.reset(seed=99)
check("same seed → same PR", obs_a["pr_id"] == obs_b["pr_id"])

# ──────────────────────────────────────────────
# 3. Easy grader
# ──────────────────────────────────────────────
print("\n[3] EasyGrader")

pr_e = get_pr("easy", 0)  # easy-001: pagination bug at line 7 and 10
grader_e = EasyGrader()

# Perfect agent: comments on both bug lines with correct severity
perfect_actions = [
    AgentAction(ActionType.COMMENT, file_path="api/pagination.py", line_number=7,
                comment_body="Off-by-one integer division", severity=Severity.ERROR),
    AgentAction(ActionType.COMMENT, file_path="api/pagination.py", line_number=10,
                comment_body="Same ceiling division bug", severity=Severity.ERROR),
    AgentAction(ActionType.REQUEST_CHANGES, verdict=Verdict.REQUEST_CHANGES,
                reasoning="Two bugs in pagination."),
]
g_perfect = grader_e.grade(pr_e, perfect_actions, n_steps=3)
check("perfect agent score > 0.85", g_perfect.total_reward > 0.85, f"got {g_perfect.total_reward}")
check("bug_found = 1.0", g_perfect.breakdown["bug_found"] == 1.0)
check("verdict_match = 1.0", g_perfect.breakdown["verdict_match"] == 1.0)

# Random agent: no useful comments
no_actions = [AgentAction(ActionType.APPROVE, verdict=Verdict.APPROVE, reasoning="LGTM")]
g_zero = grader_e.grade(pr_e, no_actions, n_steps=1)
check("wrong verdict → low score", g_zero.total_reward < 0.5, f"got {g_zero.total_reward}")

# ──────────────────────────────────────────────
# 4. Medium grader
# ──────────────────────────────────────────────
print("\n[4] MediumGrader")

pr_m = get_pr("medium", 0)  # medium-001: auth middleware
grader_m = MediumGrader()

# Good agent hits 3 of 5 issues
good_actions_m = [
    AgentAction(ActionType.EXAMINE_FILE, file_path="middleware/auth.py"),
    AgentAction(ActionType.COMMENT, file_path="middleware/auth.py", line_number=4,
                comment_body="hardcoded secret jwt must load from environment variable",
                severity=Severity.CRITICAL),
    AgentAction(ActionType.COMMENT, file_path="middleware/auth.py", line_number=12,
                comment_body="bare except exception swallows jwt errors",
                severity=Severity.WARNING),
    AgentAction(ActionType.COMMENT, file_path="middleware/rate_limit.py", line_number=9,
                comment_body="rate limit list mutation lost assign back to _hits",
                severity=Severity.ERROR),
    AgentAction(ActionType.REJECT, verdict=Verdict.REJECT,
                reasoning="Critical: hardcoded secret. Logic bug in rate limiter."),
]
g_good_m = grader_m.grade(pr_m, good_actions_m, n_steps=5)
check("medium good agent score > 0.5", g_good_m.total_reward > 0.5, f"got {g_good_m.total_reward}")
check("verdict_match = 1.0 for reject", g_good_m.breakdown["verdict_match"] == 1.0)

# ──────────────────────────────────────────────
# 5. Hard grader — security audit
# ──────────────────────────────────────────────
print("\n[5] HardGrader")

pr_h = get_pr("hard", 0)  # hard-001: SQL injection + path traversal + MD5
grader_h = HardGrader()

# Agent finds 3 of 4 critical issues
good_actions_h = [
    AgentAction(ActionType.COMMENT, file_path="api/reports.py", line_number=7,
                comment_body="path traversal os.path.join user input realpath validate",
                severity=Severity.CRITICAL),
    AgentAction(ActionType.COMMENT, file_path="api/reports.py", line_number=12,
                comment_body="sql injection f-string parameterised query placeholder",
                severity=Severity.CRITICAL),
    AgentAction(ActionType.COMMENT, file_path="api/reports.py", line_number=16,
                comment_body="md5 password hashing broken rainbow table bcrypt",
                severity=Severity.CRITICAL),
    AgentAction(ActionType.REJECT, verdict=Verdict.REJECT,
                reasoning="Multiple critical security vulnerabilities including SQLi and path traversal."),
]
g_good_h = grader_h.grade(pr_h, good_actions_h, n_steps=4)
check("hard good agent score > 0.5", g_good_h.total_reward > 0.5, f"got {g_good_h.total_reward}")
check("issue_recall > 0.5", g_good_h.breakdown["issue_recall"] > 0.5)

# hard-003: clean PR — agent must approve, not false-alarm
pr_clean = get_pr("hard", 2)  # hard-003: correct retry decorator
false_alarm_actions = [
    AgentAction(ActionType.COMMENT, file_path="utils/retry.py", line_number=15,
                comment_body="suspicious code", severity=Severity.CRITICAL),
    AgentAction(ActionType.REJECT, verdict=Verdict.REJECT, reasoning="Looks suspicious."),
]
g_fp = grader_h.grade(pr_clean, false_alarm_actions, n_steps=2)
check("false positive on clean PR penalised", g_fp.breakdown["false_pos_pen"] < 1.0)
check("wrong verdict on clean PR → low score", g_fp.total_reward < 0.3, f"got {g_fp.total_reward}")

approve_clean = [
    AgentAction(ActionType.APPROVE, verdict=Verdict.APPROVE,
                reasoning="Well-structured retry with exponential backoff. LGTM."),
]
g_clean = grader_h.grade(pr_clean, approve_clean, n_steps=1)
check("correct approve on clean PR", g_clean.breakdown["verdict_match"] == 1.0)

# ──────────────────────────────────────────────
# 6. Full episode across all difficulties
# ──────────────────────────────────────────────
print("\n[6] Full episode smoke test")

for diff in ["easy", "medium", "hard"]:
    env_t = CodeReviewEnv(difficulty=diff, seed=42)
    obs, _ = env_t.reset(seed=42)
    term = trunc = False
    steps = 0
    while not (term or trunc):
        action = env_t.action_space_sample()
        obs, reward, term, trunc, info = env_t.step(action)
        steps += 1
    final_r = info.get("total_reward", 0)
    check(f"{diff}: episode completes, reward in [0,1]",
          0.0 <= final_r <= 1.0, f"got {final_r}")

# ──────────────────────────────────────────────
print()
if errors:
    print(f"FAILED: {len(errors)} test(s): {errors}")
    sys.exit(1)
else:
    print(f"All tests passed.")
