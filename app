"""
app.py — Hugging Face Spaces Gradio interface for CodeReviewEnv.

Provides an interactive web UI for:
  - Exploring pull requests across all difficulties
  - Submitting review actions and seeing real-time reward
  - Running baseline agents and comparing scores
  - Viewing the environment spec (openenv.yaml)

Deploy: huggingface-cli upload openenv/code-review-env . --repo-type=space
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gradio as gr

from openenv import CodeReviewEnv, AgentAction, ActionType, Severity, Verdict
from openenv.dataset import all_prs

# ─────────────────────────────────────────────────────────────────────────────
# Global env state (one session — HF Spaces single-user demo)
# ─────────────────────────────────────────────────────────────────────────────

_env: CodeReviewEnv | None = None
_obs: dict | None = None


def _make_env(difficulty: str, pr_idx: int, seed: int) -> tuple[str, str, str]:
    global _env, _obs
    _env = CodeReviewEnv(difficulty=difficulty, pr_index=pr_idx, seed=seed)
    _obs, info = _env.reset(seed=seed)
    pr = _env.current_pr()
    obs_txt = json.dumps(_obs, indent=2, default=str)
    state_txt = json.dumps(_env.state(), indent=2, default=str)
    render_txt = _env.render()
    return obs_txt, state_txt, render_txt


def _fmt_diff(files: list) -> str:
    lines = []
    for f in files:
        lines.append(f"### {f['path']}  (+{f['additions']}/-{f['deletions']})  [{f['language']}]")
        lines.append("```diff")
        for dl in f.get("lines", []):
            prefix = {"+" : "+", "-": "-", " ": " "}.get(dl["change"], " ")
            lines.append(f"{prefix}{dl['line_no']:>4}  {dl['content']}")
        lines.append("```\n")
    return "\n".join(lines)


def explore_pr(difficulty: str, pr_name: str) -> tuple[str, str, str, str]:
    pr_map = {
        f"[{d}] {p.id} — {p.title[:50]}": (d, i)
        for d, prs_by_diff in [
            ("easy", [p for p in all_prs() if p.id.startswith("easy")]),
            ("medium", [p for p in all_prs() if p.id.startswith("medium")]),
            ("hard", [p for p in all_prs() if p.id.startswith("hard")]),
        ]
        for i, p in enumerate(prs_by_diff)
    }
    if pr_name not in pr_map:
        return "Select a PR above.", "", "", ""
    d, idx = pr_map[pr_name]
    obs_txt, state_txt, render_txt = _make_env(d, idx, 42)
    pr = _env.current_pr()
    diff_md = _fmt_diff(pr.files)
    meta = (
        f"**PR:** `{pr.id}` · {pr.title}\n\n"
        f"**Author:** {pr.author}  |  `{pr.base_branch}` ← `{pr.head_branch}`\n\n"
        f"**Description:** {pr.description}\n\n"
        f"**CI:** {pr.ci_status.overall.value.upper()}  |  "
        f"Tests: {pr.test_summary.passed}/{pr.test_summary.total} "
        f"({pr.test_summary.coverage_pct:.0f}% coverage)\n\n"
        f"**Repo:** {pr.repo_context.name} · {pr.repo_context.language}"
    )
    return meta, diff_md, render_txt, state_txt


def submit_action(
    action_type: str, file_path: str, line_no: int,
    comment: str, severity: str, verdict: str, reasoning: str,
) -> tuple[str, str, str]:
    global _obs
    if _env is None:
        return "No environment loaded. Select a PR first.", "", ""
    try:
        sev = Severity(severity) if severity and action_type == "comment" else None
        ver = Verdict(verdict) if verdict and action_type in ("approve","reject","request_changes") else None
        action = AgentAction(
            action_type=ActionType(action_type),
            file_path=file_path or None,
            line_number=int(line_no) if line_no else None,
            comment_body=comment or None,
            severity=sev,
            verdict=ver,
            reasoning=reasoning or None,
        )
        _obs, reward, terminated, truncated, info = _env.step(action)
        status = f"**Reward: {reward:+.4f}**"
        if terminated or truncated:
            grade = info.get("grade", {})
            status += f"\n\nEpisode ended! Total reward: **{grade.get('total', 0):.4f}**\n\n"
            status += "**Breakdown:**\n"
            for k, v in grade.get("breakdown", {}).items():
                bar = "█" * int(v * 20) + "░" * (20 - int(v * 20))
                status += f"`{k:<22}` [{bar}] `{v:.3f}`\n"
            feedback = grade.get("feedback", [])
            if feedback:
                status += "\n**Grader feedback:**\n" + "\n".join(f"- {f}" for f in feedback)
        return status, _env.render(), json.dumps(_env.state(), indent=2, default=str)
    except Exception as e:
        return f"Error: {e}", _env.render() if _env else "", ""


def run_baseline_demo(difficulty: str, agent_name: str) -> str:
    from scripts.baseline_inference import (
        RandomAgent, KeywordHeuristicAgent, LLMZeroShotAgent, evaluate_agent
    )
    agents = {
        "random": RandomAgent(42),
        "keyword_heuristic": KeywordHeuristicAgent(),
        "llm_zero_shot": LLMZeroShotAgent(),
    }
    agent = agents[agent_name]
    n = 3  # quick demo
    stats = evaluate_agent(agent, difficulty, n, seed=42)
    return json.dumps({"agent": agent_name, "difficulty": difficulty, "n_episodes": n, **stats}, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Gradio UI
# ─────────────────────────────────────────────────────────────────────────────

pr_choices = (
    [f"[easy] easy-00{i+1} — {p.title[:50]}" for i, p in
     enumerate(p for p in all_prs() if p.id.startswith("easy"))]
    + [f"[medium] medium-00{i+1} — {p.title[:50]}" for i, p in
       enumerate(p for p in all_prs() if p.id.startswith("medium"))]
    + [f"[hard] hard-00{i+1} — {p.title[:50]}" for i, p in
       enumerate(p for p in all_prs() if p.id.startswith("hard"))]
)

with gr.Blocks(title="OpenEnv — Code Review Environment", theme=gr.themes.Monochrome()) as demo:
    gr.Markdown("""
# 🔍 OpenEnv — Code Review Environment
**A real-world RL environment for AI code review agents.**
Difficulty levels: Easy → Medium → Hard · Reward: 0.0–1.0 · Full `step()` / `reset()` / `state()` API
""")

    with gr.Tabs():

        # ── Tab 1: Explore PRs ────────────────────────────────────────────
        with gr.Tab("📋 Explore PRs"):
            pr_dropdown = gr.Dropdown(choices=pr_choices, label="Select Pull Request", value=pr_choices[0])
            load_btn = gr.Button("Load PR", variant="primary")
            pr_meta = gr.Markdown()
            with gr.Row():
                with gr.Column(scale=2):
                    pr_diff = gr.Markdown(label="Diff")
                with gr.Column(scale=1):
                    env_render = gr.Textbox(label="env.render()", lines=20)
                    env_state = gr.Code(label="env.state()", language="json", lines=15)
            load_btn.click(
                explore_pr,
                inputs=[gr.Textbox(value="all", visible=False), pr_dropdown],
                outputs=[pr_meta, pr_diff, env_render, env_state],
            )

        # ── Tab 2: Interactive Review ─────────────────────────────────────
        with gr.Tab("🤖 Submit Actions"):
            gr.Markdown("Load a PR from the first tab, then submit actions here.")
            with gr.Row():
                action_type = gr.Dropdown(
                    choices=[a.value for a in ActionType],
                    value="examine_file", label="action_type"
                )
                file_path_in = gr.Textbox(label="file_path", placeholder="api/reports.py")
                line_no_in = gr.Number(label="line_number", value=None, precision=0)
            comment_in = gr.Textbox(label="comment_body", lines=3,
                                    placeholder="Describe the issue...")
            with gr.Row():
                severity_in = gr.Dropdown(
                    choices=[""] + [s.value for s in Severity],
                    value="", label="severity"
                )
                verdict_in = gr.Dropdown(
                    choices=[""] + [v.value for v in Verdict],
                    value="", label="verdict"
                )
            reasoning_in = gr.Textbox(label="reasoning (for terminal actions)", lines=2)
            step_btn = gr.Button("step(action)", variant="primary")
            step_result = gr.Markdown()
            with gr.Row():
                step_render = gr.Textbox(label="env.render()", lines=20)
                step_state = gr.Code(label="env.state()", language="json", lines=20)
            step_btn.click(
                submit_action,
                inputs=[action_type, file_path_in, line_no_in,
                        comment_in, severity_in, verdict_in, reasoning_in],
                outputs=[step_result, step_render, step_state],
            )

        # ── Tab 3: Baseline Scores ────────────────────────────────────────
        with gr.Tab("📊 Baseline Agents"):
            gr.Markdown("Run baseline agents and see reproducible scores.")
            with gr.Row():
                bl_diff = gr.Dropdown(choices=["easy","medium","hard"], value="easy", label="Difficulty")
                bl_agent = gr.Dropdown(
                    choices=["random","keyword_heuristic","llm_zero_shot"],
                    value="keyword_heuristic", label="Agent"
                )
            bl_btn = gr.Button("Run Evaluation (3 episodes)", variant="primary")
            bl_out = gr.Code(language="json", label="Results")
            bl_btn.click(run_baseline_demo, inputs=[bl_diff, bl_agent], outputs=[bl_out])

        # ── Tab 4: Spec ───────────────────────────────────────────────────
        with gr.Tab("📄 openenv.yaml"):
            spec_path = os.path.join(os.path.dirname(__file__), "openenv.yaml")
            spec_txt = open(spec_path).read() if os.path.exists(spec_path) else "spec not found"
            gr.Code(value=spec_txt, language="yaml", label="openenv.yaml")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
