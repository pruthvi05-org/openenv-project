# OpenEnv — Code Review Environment

[![HF Space](https://img.shields.io/badge/🤗%20Hugging%20Face-Space-blue)](https://huggingface.co/spaces/openenv/code-review-env)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

A **real-world reinforcement learning environment** where an AI agent acts as a senior code reviewer on GitHub-style pull requests. The agent must find bugs, security vulnerabilities, and logic errors; write structured line-level comments; assign severity labels; and produce a correct verdict.

No games, no toys — every PR is modelled on realistic software engineering scenarios with authentic diff formats, CI outputs, and ground-truth annotations.

---

## Environment Overview

| Property | Value |
|---|---|
| Domain | Software Engineering — Code Review |
| Tasks | 3 (Easy / Medium / Hard) |
| PRs in dataset | 9 curated PRs (3 per difficulty) |
| Reward range | 0.0 – 1.0 (float, per episode) |
| Partial credit | Yes — graded breakdown per component |
| Dependencies | None (pure Python 3.11+) |
| UI | Gradio (Hugging Face Spaces) |

---

## Quick Start

```python
from openenv import CodeReviewEnv, AgentAction, ActionType, Severity, Verdict

# Create environment
env = CodeReviewEnv(difficulty="medium", seed=42)

# Reset — returns (observation_dict, info_dict)
obs, info = env.reset()

# Inspect full internal state (does NOT leak ground truth)
print(env.state())

# Human-readable view
print(env.render())

# Submit actions
obs, reward, terminated, truncated, info = env.step(
    AgentAction(action_type=ActionType.EXAMINE_FILE, file_path="api/reports.py")
)

obs, reward, terminated, truncated, info = env.step(
    AgentAction(
        action_type=ActionType.COMMENT,
        file_path="api/reports.py",
        line_number=12,
        comment_body="SQL injection via f-string interpolation. Use parameterised queries.",
        severity=Severity.CRITICAL,
    )
)

obs, reward, terminated, truncated, info = env.step(
    AgentAction(
        action_type=ActionType.REJECT,
        verdict=Verdict.REJECT,
        reasoning="Critical SQL injection and path traversal vulnerabilities found.",
    )
)

print(f"Final reward: {reward:.4f}")
print(info["grade"])
```

---

## Action Space

Actions are `AgentAction` dataclass instances with the following fields:

| Field | Type | Required for |
|---|---|---|
| `action_type` | `ActionType` enum | always |
| `file_path` | `str \| None` | `comment`, `examine_file` |
| `line_number` | `int \| None` | `comment` |
| `comment_body` | `str \| None` | `comment` |
| `severity` | `Severity` enum | `comment` |
| `verdict` | `Verdict` enum | `approve`, `reject`, `request_changes` |
| `reasoning` | `str \| None` | terminal actions |

### ActionType values

| Value | Description | Terminal? |
|---|---|---|
| `examine_file` | Read a file's full diff (shaped reward: +0.02 per new file) | No |
| `run_check` | Run a named analysis check (+0.01 per unique check) | No |
| `comment` | Place a line-level review comment | No |
| `approve` | Approve the PR — triggers grading | **Yes** |
| `request_changes` | Request changes — triggers grading | **Yes** |
| `reject` | Reject the PR outright — triggers grading | **Yes** |

### Severity enum
`info` · `warning` · `error` · `critical`

### Verdict enum
`approve` · `request_changes` · `reject`

---

## Observation Space

`reset()` and `step()` return a Python `dict` with the following structure:

```python
{
    "pr_id":          str,           # e.g. "medium-001"
    "pr_title":       str,
    "pr_description": str,
    "author":         str,
    "base_branch":    str,
    "head_branch":    str,
    "files_changed": [               # list of FileDiff dicts
        {
            "path":       str,
            "language":   str,
            "additions":  int,
            "deletions":  int,
            "is_new_file": bool,
            "lines": [               # list of DiffLine dicts
                {"line_no": int, "content": str, "change": "+"|"-"|" "}
            ]
        }
    ],
    "ci_status": {
        "overall": "passing"|"failing"|"pending",
        "checks": [{"name": str, "state": str, "message": str}]
    },
    "test_summary": {
        "total": int, "passed": int, "failed": int,
        "coverage_pct": float, "failed_test_names": [str]
    },
    "repo_context": {
        "name": str, "language": str, "description": str,
        "has_security_policy": bool, "coding_standards": [str]
    },
    "step_history":   [AgentAction dicts],
    "examined_files": [str],
    "steps_remaining": int,
}
```

Ground truth is **never included** in the observation.

---

## Reward Functions

All rewards are in `[0.0, 1.0]`.

### Easy — Spot the Bug (max 10 steps)

| Component | Weight | Description |
|---|---|---|
| `bug_found` | 0.50 | Agent commented within ±2 lines of each gold bug |
| `severity_match` | 0.25 | Severity label within 1 tier of ground truth |
| `verdict_match` | 0.25 | Exact verdict match (approve/request_changes/reject) |

### Medium — Full PR Review (max 25 steps)

| Component | Weight | Description |
|---|---|---|
| `bug_f1` | 0.35 | F1 over (file, line, category) tuples |
| `comment_quality` | 0.20 | Jaccard token similarity vs. gold descriptions |
| `severity_macro` | 0.20 | Per-issue severity tier accuracy (macro average) |
| `verdict_match` | 0.15 | Correct final verdict |
| `efficiency` | 0.10 | Bonus for resolving in fewer steps |

### Hard — Security Audit (max 40 steps)

| Component | Weight | Description |
|---|---|---|
| `issue_recall` | 0.40 | Recall over security issues (missing one is very costly) |
| `cvss_accuracy` | 0.20 | CVSS tier accuracy per security issue |
| `mitigation_qual` | 0.20 | Keyword overlap with gold suggested_fix |
| `verdict_match` | 0.15 | Correct verdict |
| `false_pos_pen` | 0.05 | Penalty for flagging clean code as CRITICAL |

### Shaped intermediate rewards (non-terminal steps)
- `+0.02` for first examination of each unique file
- `+0.01` for each unique check run
- `+0.005` for commenting on an already-examined file
- `-0.005` for commenting on an unexamined file

---

## Tasks & Scenarios

### Easy PRs
| ID | Scenario | Bug |
|---|---|---|
| `easy-001` | Pagination helper | Off-by-one: integer division loses last page |
| `easy-002` | Config class | Mutable default argument `overrides={}` |
| `easy-003` | User profile loader (JS) | Null dereference after DB lookup |

### Medium PRs
| ID | Scenario | Issues |
|---|---|---|
| `medium-001` | JWT auth + rate limiting | Hardcoded secret, bare except, rate-limit mutation bug, thread unsafety |
| `medium-002` | Go worker pool | Goroutine leak on shutdown, silent error swallowing, dead code |
| `medium-003` | React MessageRenderer | XSS via dangerouslySetInnerHTML, missing useEffect dep, `any` typing |

### Hard PRs
| ID | Scenario | Vulnerabilities |
|---|---|---|
| `hard-001` | Reports API + user management | Path traversal, 2× SQL injection, MD5 password hashing |
| `hard-002` | Webhook processor + cache | pickle RCE (CVSS 10.0), SSRF, timing attack, cache race condition |
| `hard-003` | Retry decorator (**clean**) | None — tests false-positive rate |

---

## Baseline Scores (seed=42, 9 episodes)

| Agent | Easy | Medium | Hard |
|---|---|---|---|
| Random | 0.111 ± 0.247 | 0.164 ± 0.077 | 0.106 ± 0.083 |
| Keyword heuristic | 0.365 ± 0.502 | 0.523 ± 0.156 | 0.501 ± 0.217 |
| LLM zero-shot (mock) | **0.881 ± 0.175** | **0.735 ± 0.026** | **0.618 ± 0.299** |

Run baselines yourself:
```bash
python scripts/baseline_inference.py
python scripts/baseline_inference.py --difficulty hard --agent keyword --n 20
```

---

## Setup

### Local (no dependencies beyond Python 3.11+)
```bash
git clone https://huggingface.co/spaces/openenv/code-review-env
cd code-review-env
python tests/test_env.py          # 31 tests
python scripts/baseline_inference.py
```

### With Gradio UI
```bash
pip install gradio==4.44.1
python app.py
# → http://localhost:7860
```

### Docker
```bash
docker build -t openenv .
docker run -p 7860:7860 openenv
```

---

## Deploying to Hugging Face Spaces

1. Create a new Space at https://huggingface.co/new-space
   - SDK: **Gradio**
   - Hardware: CPU Basic (free tier works)

2. Push:
```bash
git remote add space https://huggingface.co/spaces/YOUR_USERNAME/code-review-env
git push space main
```

The `Dockerfile` is pre-configured for HF Spaces (port 7860, non-root user).

---

## Project Structure

```
openenv/
├── openenv.yaml              # Full environment spec
├── app.py                    # Gradio UI (HF Spaces entry point)
├── Dockerfile                # HF Spaces deployment
├── requirements.txt          # gradio only
│
├── openenv/
│   ├── __init__.py           # Public API
│   ├── models.py             # Typed dataclasses: PR, FileDiff, AgentAction…
│   ├── dataset.py            # 9 curated PRs with ground-truth annotations
│   ├── env.py                # CodeReviewEnv (reset/step/state/render)
│   └── graders.py            # EasyGrader, MediumGrader, HardGrader
│
├── scripts/
│   └── baseline_inference.py # Reproducible baseline evaluation
│
└── tests/
    └── test_env.py           # 31 unit + integration tests
```

---

## Extending the Environment

### Adding new PRs

```python
# openenv/dataset.py
def _easy_4() -> PullRequest:
    return PullRequest(
        id="easy-004",
        title="feat: ...",
        ...
        ground_truth=GroundTruth(
            issues=[GroundTruthIssue(...)],
            correct_verdict=Verdict.REQUEST_CHANGES,
        )
    )

EASY_PRS.append(_easy_4)
```

### Custom agents

```python
class MyAgent:
    def act(self, obs: dict, env: CodeReviewEnv) -> AgentAction:
        # obs["files_changed"] → list of file diffs
        # obs["step_history"] → previous actions
        # obs["examined_files"] → already examined
        ...
        return AgentAction(action_type=ActionType.COMMENT, ...)
```

---

## License

MIT
