"""
dataset.py — curated pull request dataset for CodeReviewEnv.

Each PR is a realistic software engineering scenario with:
  - Real-looking diffs (Python, JavaScript, Go)
  - Ground-truth bug/issue annotations
  - CI status and test summaries
  - Correct verdicts

Difficulties:
  easy   → single file, one obvious bug
  medium → multi-file, mixed issues (bugs + security + style)
  hard   → subtle security vulnerabilities, race conditions, crypto misuse
"""
from __future__ import annotations

from openenv.models import (
    PullRequest, FileDiff, DiffLine, CIStatus, CIState, CICheck,
    TestSummary, RepoContext, GroundTruth, GroundTruthIssue,
    IssueCategory, Severity, Verdict,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _lines(text: str, start: int = 1, change: str = " ") -> list[DiffLine]:
    result = []
    for i, line in enumerate(text.strip().split("\n"), start=start):
        result.append(DiffLine(line_no=i, content=line, change=change))
    return result


def _diff(added_text: str, path: str, lang: str = "python",
          ctx_before: str = "", ctx_after: str = "") -> FileDiff:
    lines = []
    n = 1
    if ctx_before:
        for l in ctx_before.strip().split("\n"):
            lines.append(DiffLine(line_no=n, content=l, change=" "))
            n += 1
    for l in added_text.strip().split("\n"):
        lines.append(DiffLine(line_no=n, content=l, change="+"))
        n += 1
    if ctx_after:
        for l in ctx_after.strip().split("\n"):
            lines.append(DiffLine(line_no=n, content=l, change=" "))
            n += 1
    adds = sum(1 for dl in lines if dl.change == "+")
    return FileDiff(path=path, language=lang, additions=adds, deletions=0, lines=lines)


# ─────────────────────────────────────────────────────────────────────────────
# EASY PRs
# ─────────────────────────────────────────────────────────────────────────────

def _easy_1() -> PullRequest:
    """Off-by-one error in pagination."""
    file1 = FileDiff(
        path="api/pagination.py", language="python",
        additions=12, deletions=8,
        lines=[
            DiffLine(1,  "def paginate(items, page, page_size=10):", " "),
            DiffLine(2,  '    """Return items for a given page (1-indexed)."""', " "),
            DiffLine(3,  "    if page < 1:", " "),
            DiffLine(4,  "        raise ValueError('page must be >= 1')", " "),
            DiffLine(5,  "    start = (page - 1) * page_size", "+"),
            DiffLine(6,  "    end = start + page_size", "+"),
            DiffLine(7,  "    return items[start:end], len(items) // page_size", "+"),
            DiffLine(8,  "", " "),
            DiffLine(9,  "def total_pages(count, page_size=10):", " "),
            DiffLine(10, "    return count // page_size", "+"),
        ]
    )
    gt = GroundTruth(
        issues=[
            GroundTruthIssue(
                file_path="api/pagination.py", line_no=7,
                category=IssueCategory.BUG, severity=Severity.ERROR,
                description=(
                    "Integer division drops the last partial page. "
                    "If len(items)=25 and page_size=10, total_pages returns 2 instead of 3."
                ),
                suggested_fix="return (count + page_size - 1) // page_size  # ceiling division",
            ),
            GroundTruthIssue(
                file_path="api/pagination.py", line_no=10,
                category=IssueCategory.BUG, severity=Severity.ERROR,
                description="Same ceiling-division bug in total_pages helper.",
                suggested_fix="return math.ceil(count / page_size)",
            ),
        ],
        correct_verdict=Verdict.REQUEST_CHANGES,
        explanation="Two off-by-one bugs in pagination math; last page of results unreachable.",
    )
    return PullRequest(
        id="easy-001",
        title="feat: add pagination helper to API layer",
        description="Adds `paginate()` and `total_pages()` utilities. Used by `/items` endpoint.",
        author="dev-alice",
        base_branch="main", head_branch="feat/pagination",
        files=[file1],
        ci_status=CIStatus(
            overall=CIState.PASSING,
            checks=[CICheck("unit-tests", CIState.PASSING, "42 passed"), CICheck("lint", CIState.PASSING)]
        ),
        test_summary=TestSummary(total=42, passed=42, failed=0, coverage_pct=71.0),
        repo_context=RepoContext("shop-api", "python", "E-commerce REST API", stars=120, contributors=4),
        ground_truth=gt,
    )


def _easy_2() -> PullRequest:
    """Mutable default argument — classic Python footgun."""
    file1 = FileDiff(
        path="utils/config.py", language="python",
        additions=10, deletions=0,
        lines=[
            DiffLine(1,  "class Config:", " "),
            DiffLine(2,  "    def __init__(self, overrides={}):", "+"),
            DiffLine(3,  "        self.data = overrides", "+"),
            DiffLine(4,  "", " "),
            DiffLine(5,  "    def set(self, key, value):", " "),
            DiffLine(6,  "        self.data[key] = value", "+"),
            DiffLine(7,  "", " "),
            DiffLine(8,  "    def get(self, key, default=None):", " "),
            DiffLine(9,  "        return self.data.get(key, default)", " "),
        ]
    )
    gt = GroundTruth(
        issues=[
            GroundTruthIssue(
                file_path="utils/config.py", line_no=2,
                category=IssueCategory.BUG, severity=Severity.ERROR,
                description=(
                    "Mutable default argument `overrides={}` is shared across all "
                    "Config instances. Mutations via `set()` will leak between instances."
                ),
                suggested_fix="def __init__(self, overrides=None):\n    self.data = dict(overrides or {})",
            ),
        ],
        correct_verdict=Verdict.REQUEST_CHANGES,
        explanation="Classic Python mutable default arg bug; state leaks across instances.",
    )
    return PullRequest(
        id="easy-002",
        title="refactor: extract Config class from scattered globals",
        description="Consolidates app config into a single Config class.",
        author="dev-bob",
        base_branch="main", head_branch="refactor/config-class",
        files=[file1],
        ci_status=CIStatus(CIState.PASSING, [CICheck("tests", CIState.PASSING, "18 passed")]),
        test_summary=TestSummary(total=18, passed=18, coverage_pct=55.0),
        repo_context=RepoContext("webapp", "python", "Flask web app"),
        ground_truth=gt,
    )


def _easy_3() -> PullRequest:
    """Null dereference / missing None check in JS."""
    file1 = FileDiff(
        path="src/userProfile.js", language="javascript",
        additions=14, deletions=0,
        lines=[
            DiffLine(1,  "async function loadUserProfile(userId) {", " "),
            DiffLine(2,  "  const user = await db.users.findById(userId);", "+"),
            DiffLine(3,  "  const displayName = user.profile.displayName;", "+"),
            DiffLine(4,  "  const email = user.email.toLowerCase();", "+"),
            DiffLine(5,  "  return { displayName, email };", "+"),
            DiffLine(6,  "}", " "),
            DiffLine(7,  "", " "),
            DiffLine(8,  "function formatUserCard(user) {", " "),
            DiffLine(9,  "  return `<div class='card'>${user.profile.avatar}</div>`;", "+"),
            DiffLine(10, "}", " "),
        ]
    )
    gt = GroundTruth(
        issues=[
            GroundTruthIssue(
                file_path="src/userProfile.js", line_no=2,
                category=IssueCategory.BUG, severity=Severity.ERROR,
                description="No null-check after `findById` — returns null if user not found. Lines 3-4 will throw TypeError.",
                suggested_fix="if (!user) throw new NotFoundError(`User ${userId} not found`);",
            ),
            GroundTruthIssue(
                file_path="src/userProfile.js", line_no=3,
                category=IssueCategory.BUG, severity=Severity.WARNING,
                description="`user.profile` may be null/undefined for accounts with incomplete profiles.",
                suggested_fix="const displayName = user.profile?.displayName ?? 'Anonymous';",
            ),
        ],
        correct_verdict=Verdict.REQUEST_CHANGES,
        explanation="Unguarded null dereferences will crash in production for missing users/profiles.",
    )
    return PullRequest(
        id="easy-003",
        title="feat: user profile loader and card formatter",
        description="Loads user profiles from DB and formats for frontend display.",
        author="dev-carol",
        base_branch="main", head_branch="feat/user-profile",
        files=[file1],
        ci_status=CIStatus(CIState.FAILING, [
            CICheck("unit-tests", CIState.FAILING, "1 failed: test_missing_user"),
            CICheck("lint", CIState.PASSING),
        ]),
        test_summary=TestSummary(total=10, passed=9, failed=1, coverage_pct=48.0,
                                 failed_test_names=["test_missing_user"]),
        repo_context=RepoContext("frontend-svc", "javascript", "React/Node.js frontend service"),
        ground_truth=gt,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MEDIUM PRs
# ─────────────────────────────────────────────────────────────────────────────

def _medium_1() -> PullRequest:
    """Auth middleware: hardcoded secret + missing rate limit + logic bug."""
    file1 = FileDiff(
        path="middleware/auth.py", language="python",
        additions=20, deletions=5,
        lines=[
            DiffLine(1,  "import jwt", " "),
            DiffLine(2,  "import hashlib", " "),
            DiffLine(3,  "", " "),
            DiffLine(4,  "SECRET = 'supersecret123'", "+"),
            DiffLine(5,  "", " "),
            DiffLine(6,  "def verify_token(token):", " "),
            DiffLine(7,  "    try:", " "),
            DiffLine(8,  "        payload = jwt.decode(token, SECRET, algorithms=['HS256'])", "+"),
            DiffLine(9,  "        return payload", "+"),
            DiffLine(10, "    except jwt.ExpiredSignatureError:", " "),
            DiffLine(11, "        return None", "+"),
            DiffLine(12, "    except Exception:", "+"),
            DiffLine(13, "        return None", "+"),
        ]
    )
    file2 = FileDiff(
        path="middleware/rate_limit.py", language="python",
        additions=18, deletions=0,
        lines=[
            DiffLine(1,  "from collections import defaultdict", " "),
            DiffLine(2,  "import time", " "),
            DiffLine(3,  "", " "),
            DiffLine(4,  "_hits = defaultdict(list)", "+"),
            DiffLine(5,  "", " "),
            DiffLine(6,  "def check_rate_limit(user_id, limit=100, window=60):", "+"),
            DiffLine(7,  "    now = time.time()", "+"),
            DiffLine(8,  "    hits = _hits[user_id]", "+"),
            DiffLine(9,  "    hits = [h for h in hits if now - h < window]", "+"),
            DiffLine(10, "    if len(hits) >= limit:", "+"),
            DiffLine(11, "        return False", "+"),
            DiffLine(12, "    hits.append(now)", "+"),
            DiffLine(13, "    return True", "+"),
        ]
    )
    file3 = FileDiff(
        path="tests/test_auth.py", language="python",
        additions=8, deletions=0,
        lines=[
            DiffLine(1,  "def test_valid_token():", "+"),
            DiffLine(2,  "    token = jwt.encode({'sub': '1'}, 'supersecret123', 'HS256')", "+"),
            DiffLine(3,  "    assert verify_token(token) is not None", "+"),
        ]
    )
    gt = GroundTruth(
        issues=[
            GroundTruthIssue(
                file_path="middleware/auth.py", line_no=4,
                category=IssueCategory.SECURITY, severity=Severity.CRITICAL,
                description="Hardcoded JWT secret in source code. Will be committed to version control.",
                suggested_fix="SECRET = os.environ['JWT_SECRET']  # load from env",
            ),
            GroundTruthIssue(
                file_path="middleware/auth.py", line_no=12,
                category=IssueCategory.BUG, severity=Severity.WARNING,
                description="Bare `except Exception` silently swallows all JWT errors including tampered tokens. Should distinguish InvalidSignatureError.",
                suggested_fix="except jwt.InvalidTokenError: return None",
            ),
            GroundTruthIssue(
                file_path="middleware/rate_limit.py", line_no=9,
                category=IssueCategory.BUG, severity=Severity.ERROR,
                description="_hits[user_id] is not updated after filtering — mutation is lost because a new list is assigned to local `hits`, not to _hits[user_id].",
                suggested_fix="_hits[user_id] = [h for h in hits if now - h < window]",
            ),
            GroundTruthIssue(
                file_path="middleware/rate_limit.py", line_no=4,
                category=IssueCategory.RACE_CONDITION, severity=Severity.WARNING,
                description="Module-level `_hits` dict is not thread-safe. Concurrent requests can corrupt state.",
                suggested_fix="Use threading.Lock() or switch to Redis-backed rate limiter.",
            ),
            GroundTruthIssue(
                file_path="tests/test_auth.py", line_no=2,
                category=IssueCategory.SECURITY, severity=Severity.ERROR,
                description="Test hardcodes the same secret, coupling tests to the leaked secret value.",
                suggested_fix="Use a test-only fixture secret from environment or conftest.",
            ),
        ],
        correct_verdict=Verdict.REJECT,
        explanation="Critical security issue (hardcoded secret) + logic bug in rate limiter make this unsafe to merge.",
    )
    return PullRequest(
        id="medium-001",
        title="feat: JWT authentication middleware with rate limiting",
        description="Adds token verification and per-user rate limiting to all API routes.",
        author="dev-dave",
        base_branch="main", head_branch="feat/auth-middleware",
        files=[file1, file2, file3],
        ci_status=CIStatus(CIState.PASSING, [
            CICheck("tests", CIState.PASSING, "31 passed"),
            CICheck("security-scan", CIState.PASSING, "No known CVEs"),
        ]),
        test_summary=TestSummary(total=31, passed=31, coverage_pct=61.0),
        repo_context=RepoContext("payments-api", "python", "Payments processing API",
                                 has_security_policy=True, stars=430, contributors=12,
                                 coding_standards=["PEP8", "OWASP Top 10"]),
        ground_truth=gt,
    )


def _medium_2() -> PullRequest:
    """Go service: goroutine leak + missing error propagation + dead code."""
    file1 = FileDiff(
        path="internal/worker/pool.go", language="go",
        additions=35, deletions=0,
        lines=[
            DiffLine(1,  "package worker", " "),
            DiffLine(2,  "", " "),
            DiffLine(3,  "import \"sync\"", " "),
            DiffLine(4,  "", " "),
            DiffLine(5,  "type Pool struct {", "+"),
            DiffLine(6,  "    jobs    chan func()", "+"),
            DiffLine(7,  "    wg      sync.WaitGroup", "+"),
            DiffLine(8,  "}", "+"),
            DiffLine(9,  "", " "),
            DiffLine(10, "func NewPool(size int) *Pool {", "+"),
            DiffLine(11, "    p := &Pool{jobs: make(chan func(), 100)}", "+"),
            DiffLine(12, "    for i := 0; i < size; i++ {", "+"),
            DiffLine(13, "        go func() {", "+"),
            DiffLine(14, "            for job := range p.jobs {", "+"),
            DiffLine(15, "                job()", "+"),
            DiffLine(16, "            }", "+"),
            DiffLine(17, "        }()", "+"),
            DiffLine(18, "    }", "+"),
            DiffLine(19, "    return p", "+"),
            DiffLine(20, "}", "+"),
            DiffLine(21, "", " "),
            DiffLine(22, "func (p *Pool) Submit(job func()) {", "+"),
            DiffLine(23, "    p.jobs <- job", "+"),
            DiffLine(24, "}", "+"),
            DiffLine(25, "", " "),
            DiffLine(26, "func (p *Pool) Stop() {", "+"),
            DiffLine(27, "    close(p.jobs)", "+"),
            DiffLine(28, "}", "+"),
        ]
    )
    file2 = FileDiff(
        path="internal/worker/processor.go", language="go",
        additions=20, deletions=0,
        lines=[
            DiffLine(1,  "func ProcessBatch(items []Item) error {", "+"),
            DiffLine(2,  "    pool := NewPool(4)", "+"),
            DiffLine(3,  "    for _, item := range items {", "+"),
            DiffLine(4,  "        item := item // capture", "+"),
            DiffLine(5,  "        pool.Submit(func() {", "+"),
            DiffLine(6,  "            err := processItem(item)", "+"),
            DiffLine(7,  "            if err != nil {", "+"),
            DiffLine(8,  "                fmt.Println(\"error:\", err)", "+"),
            DiffLine(9,  "            }", "+"),
            DiffLine(10, "        })", "+"),
            DiffLine(11, "    }", "+"),
            DiffLine(12, "    pool.Stop()", "+"),
            DiffLine(13, "    return nil", "+"),
            DiffLine(14, "}", "+"),
            DiffLine(15, "", " "),
            DiffLine(16, "func legacyProcess(item Item) error {  // TODO: remove", "+"),
            DiffLine(17, "    return nil", "+"),
            DiffLine(18, "}", "+"),
        ]
    )
    gt = GroundTruth(
        issues=[
            GroundTruthIssue(
                file_path="internal/worker/pool.go", line_no=27,
                category=IssueCategory.BUG, severity=Severity.ERROR,
                description="Stop() closes the channel but doesn't wait for goroutines to finish draining. Jobs in-flight are abandoned; WaitGroup is never used.",
                suggested_fix="p.wg.Wait() after close(p.jobs); add p.wg.Add(1)/p.wg.Done() in goroutine.",
            ),
            GroundTruthIssue(
                file_path="internal/worker/processor.go", line_no=8,
                category=IssueCategory.BUG, severity=Severity.ERROR,
                description="Errors from processItem are printed but not propagated. ProcessBatch always returns nil even if all items fail.",
                suggested_fix="Use an errgroup or channel to collect errors and return the first/aggregated error.",
            ),
            GroundTruthIssue(
                file_path="internal/worker/processor.go", line_no=16,
                category=IssueCategory.DEAD_CODE, severity=Severity.INFO,
                description="`legacyProcess` is unreachable dead code marked TODO:remove. Should be deleted before merge.",
                suggested_fix="Delete the function.",
            ),
        ],
        correct_verdict=Verdict.REQUEST_CHANGES,
        explanation="Goroutines leak on shutdown + silent error swallowing are correctness bugs.",
    )
    return PullRequest(
        id="medium-002",
        title="feat: worker pool for batch item processing",
        description="Replaces sequential processing with a goroutine pool. 4x throughput improvement.",
        author="dev-eve",
        base_branch="main", head_branch="feat/worker-pool",
        files=[file1, file2],
        ci_status=CIStatus(CIState.PASSING, [CICheck("go-test", CIState.PASSING, "PASS")]),
        test_summary=TestSummary(total=22, passed=22, coverage_pct=58.0),
        repo_context=RepoContext("data-pipeline", "go", "Real-time data processing service", stars=210),
        ground_truth=gt,
    )


def _medium_3() -> PullRequest:
    """React: XSS via dangerouslySetInnerHTML + missing dep in useEffect."""
    file1 = FileDiff(
        path="src/components/MessageRenderer.tsx", language="typescript",
        additions=22, deletions=0,
        lines=[
            DiffLine(1,  "import React, { useEffect, useState } from 'react';", " "),
            DiffLine(2,  "", " "),
            DiffLine(3,  "interface Props { userId: string; }", " "),
            DiffLine(4,  "", " "),
            DiffLine(5,  "export function MessageRenderer({ userId }: Props) {", "+"),
            DiffLine(6,  "  const [messages, setMessages] = useState([]);", "+"),
            DiffLine(7,  "", " "),
            DiffLine(8,  "  useEffect(() => {", "+"),
            DiffLine(9,  "    fetch(`/api/messages/${userId}`)", "+"),
            DiffLine(10, "      .then(r => r.json())", "+"),
            DiffLine(11, "      .then(setMessages);", "+"),
            DiffLine(12, "  }, []);", "+"),
            DiffLine(13, "", " "),
            DiffLine(14, "  return (", "+"),
            DiffLine(15, "    <div>", "+"),
            DiffLine(16, "      {messages.map((m: any) => (", "+"),
            DiffLine(17, "        <div key={m.id}", "+"),
            DiffLine(18, "          dangerouslySetInnerHTML={{ __html: m.content }}", "+"),
            DiffLine(19, "        />", "+"),
            DiffLine(20, "      ))}", "+"),
            DiffLine(21, "    </div>", "+"),
            DiffLine(22, "  );", "+"),
            DiffLine(23, "}", "+"),
        ]
    )
    gt = GroundTruth(
        issues=[
            GroundTruthIssue(
                file_path="src/components/MessageRenderer.tsx", line_no=18,
                category=IssueCategory.SECURITY, severity=Severity.CRITICAL,
                description="dangerouslySetInnerHTML with unsanitised server content enables stored XSS. Attacker can inject arbitrary JS via message content.",
                suggested_fix="Sanitize with DOMPurify: __html: DOMPurify.sanitize(m.content)",
            ),
            GroundTruthIssue(
                file_path="src/components/MessageRenderer.tsx", line_no=12,
                category=IssueCategory.BUG, severity=Severity.WARNING,
                description="useEffect dependency array is empty `[]` but the effect uses `userId`. If userId changes, messages will not reload.",
                suggested_fix="}, [userId]);",
            ),
            GroundTruthIssue(
                file_path="src/components/MessageRenderer.tsx", line_no=16,
                category=IssueCategory.STYLE, severity=Severity.WARNING,
                description="`m: any` disables TypeScript type checking. Define a Message interface instead.",
                suggested_fix="interface Message { id: string; content: string; }\n(m: Message)",
            ),
        ],
        correct_verdict=Verdict.REJECT,
        explanation="Stored XSS via dangerouslySetInnerHTML is a critical security issue; must not merge.",
    )
    return PullRequest(
        id="medium-003",
        title="feat: render user messages with rich HTML content",
        description="Renders messages that may contain formatted HTML from the server.",
        author="dev-frank",
        base_branch="main", head_branch="feat/rich-messages",
        files=[file1],
        ci_status=CIStatus(CIState.PASSING, [
            CICheck("jest", CIState.PASSING, "45 passed"),
            CICheck("eslint", CIState.PASSING),
        ]),
        test_summary=TestSummary(total=45, passed=45, coverage_pct=67.0),
        repo_context=RepoContext("chat-app", "typescript", "Real-time chat application",
                                 has_security_policy=True, stars=890,
                                 coding_standards=["OWASP", "React Best Practices"]),
        ground_truth=gt,
    )


# ─────────────────────────────────────────────────────────────────────────────
# HARD PRs — subtle security vulnerabilities
# ─────────────────────────────────────────────────────────────────────────────

def _hard_1() -> PullRequest:
    """SQL injection via f-string + path traversal + weak crypto."""
    file1 = FileDiff(
        path="api/reports.py", language="python",
        additions=30, deletions=0,
        lines=[
            DiffLine(1,  "import sqlite3, hashlib, os", " "),
            DiffLine(2,  "from flask import request, send_file", " "),
            DiffLine(3,  "", " "),
            DiffLine(4,  "def get_report(report_name):", "+"),
            DiffLine(5,  "    # Serve report files from reports directory", "+"),
            DiffLine(6,  "    base = '/var/app/reports'", "+"),
            DiffLine(7,  "    path = os.path.join(base, report_name)", "+"),
            DiffLine(8,  "    return send_file(path)", "+"),
            DiffLine(9,  "", " "),
            DiffLine(10, "def search_users(query):", "+"),
            DiffLine(11, "    conn = sqlite3.connect('app.db')", "+"),
            DiffLine(12, "    sql = f\"SELECT * FROM users WHERE name LIKE '%{query}%'\"", "+"),
            DiffLine(13, "    return conn.execute(sql).fetchall()", "+"),
            DiffLine(14, "", " "),
            DiffLine(15, "def hash_password(password):", "+"),
            DiffLine(16, "    return hashlib.md5(password.encode()).hexdigest()", "+"),
            DiffLine(17, "", " "),
            DiffLine(18, "def verify_password(password, stored_hash):", "+"),
            DiffLine(19, "    return hash_password(password) == stored_hash", "+"),
            DiffLine(20, "", " "),
            DiffLine(21, "def create_user(username, password, role='user'):", "+"),
            DiffLine(22, "    sql = f\"INSERT INTO users VALUES ('{username}', '{hash_password(password)}', '{role}')\"", "+"),
            DiffLine(23, "    conn = sqlite3.connect('app.db')", "+"),
            DiffLine(24, "    conn.execute(sql)", "+"),
            DiffLine(25, "    conn.commit()", "+"),
        ]
    )
    gt = GroundTruth(
        issues=[
            GroundTruthIssue(
                file_path="api/reports.py", line_no=7,
                category=IssueCategory.SECURITY, severity=Severity.CRITICAL,
                description="Path traversal: os.path.join does not prevent `../` sequences. Attacker can read /etc/passwd via report_name='../../../../etc/passwd'.",
                suggested_fix="path = os.path.realpath(os.path.join(base, report_name))\nif not path.startswith(base): abort(400)",
                cvss_score=7.5,
            ),
            GroundTruthIssue(
                file_path="api/reports.py", line_no=12,
                category=IssueCategory.SECURITY, severity=Severity.CRITICAL,
                description="SQL injection via f-string interpolation in LIKE query. Attacker can dump entire DB or bypass auth with `' OR '1'='1`.",
                suggested_fix="cursor.execute(\"SELECT * FROM users WHERE name LIKE ?\", (f'%{query}%',))",
                cvss_score=9.8,
            ),
            GroundTruthIssue(
                file_path="api/reports.py", line_no=16,
                category=IssueCategory.SECURITY, severity=Severity.CRITICAL,
                description="MD5 for password hashing is cryptographically broken. Rainbow tables can crack MD5 hashes in seconds. No salt.",
                suggested_fix="import bcrypt; return bcrypt.hashpw(password.encode(), bcrypt.gensalt())",
                cvss_score=8.2,
            ),
            GroundTruthIssue(
                file_path="api/reports.py", line_no=22,
                category=IssueCategory.SECURITY, severity=Severity.CRITICAL,
                description="Second SQL injection in create_user via f-string. Username/role fields are injectable.",
                suggested_fix="conn.execute('INSERT INTO users VALUES (?,?,?)', (username, hash_password(password), role))",
                cvss_score=9.8,
            ),
        ],
        correct_verdict=Verdict.REJECT,
        explanation="Four critical security vulnerabilities: 2× SQLi, path traversal, broken crypto. Must not merge under any circumstances.",
    )
    return PullRequest(
        id="hard-001",
        title="feat: reports API and user management endpoints",
        description="Adds file-based report serving, user search, and user creation. Refactors password storage.",
        author="dev-gary",
        base_branch="main", head_branch="feat/reports-api",
        files=[file1],
        ci_status=CIStatus(CIState.PASSING, [
            CICheck("tests", CIState.PASSING, "55 passed"),
            CICheck("bandit", CIState.PASSING, "No issues (medium+)"),  # scanner missed it
        ]),
        test_summary=TestSummary(total=55, passed=55, coverage_pct=74.0),
        repo_context=RepoContext("admin-portal", "python", "Internal admin portal",
                                 has_security_policy=True, stars=0, contributors=3,
                                 coding_standards=["OWASP Top 10", "PCI-DSS"]),
        ground_truth=gt,
    )


def _hard_2() -> PullRequest:
    """Insecure deserialization + SSRF + timing attack."""
    file1 = FileDiff(
        path="services/webhook.py", language="python",
        additions=35, deletions=0,
        lines=[
            DiffLine(1,  "import pickle, base64, requests", " "),
            DiffLine(2,  "from flask import request", " "),
            DiffLine(3,  "", " "),
            DiffLine(4,  "def process_webhook(payload):", "+"),
            DiffLine(5,  "    # Decode and restore state object from client", "+"),
            DiffLine(6,  "    data = base64.b64decode(payload['state'])", "+"),
            DiffLine(7,  "    state = pickle.loads(data)", "+"),
            DiffLine(8,  "    return handle_state(state)", "+"),
            DiffLine(9,  "", " "),
            DiffLine(10, "def fetch_external_resource(url):", "+"),
            DiffLine(11, "    # Fetch content from integrations", "+"),
            DiffLine(12, "    resp = requests.get(url, timeout=10)", "+"),
            DiffLine(13, "    return resp.text", "+"),
            DiffLine(14, "", " "),
            DiffLine(15, "def verify_api_key(provided, expected):", "+"),
            DiffLine(16, "    return provided == expected", "+"),
        ]
    )
    file2 = FileDiff(
        path="services/cache.py", language="python",
        additions=20, deletions=0,
        lines=[
            DiffLine(1,  "import threading", " "),
            DiffLine(2,  "", " "),
            DiffLine(3,  "_cache = {}", "+"),
            DiffLine(4,  "_lock = threading.Lock()", "+"),
            DiffLine(5,  "", " "),
            DiffLine(6,  "def cache_set(key, value, ttl=300):", "+"),
            DiffLine(7,  "    _cache[key] = {'value': value, 'expires': time.time() + ttl}", "+"),
            DiffLine(8,  "", " "),
            DiffLine(9,  "def cache_get(key):", "+"),
            DiffLine(10, "    entry = _cache.get(key)", "+"),
            DiffLine(11, "    if entry and entry['expires'] > time.time():", "+"),
            DiffLine(12, "        return entry['value']", "+"),
            DiffLine(13, "    return None", "+"),
            DiffLine(14, "", " "),
            DiffLine(15, "def cache_invalidate(key):", "+"),
            DiffLine(16, "    if key in _cache:", "+"),
            DiffLine(17, "        del _cache[key]", "+"),
            DiffLine(18, "}", "+"),
        ]
    )
    gt = GroundTruth(
        issues=[
            GroundTruthIssue(
                file_path="services/webhook.py", line_no=7,
                category=IssueCategory.SECURITY, severity=Severity.CRITICAL,
                description="Insecure deserialization: pickle.loads on untrusted client data allows arbitrary code execution (RCE). Attacker can craft payload to run any OS command.",
                suggested_fix="Use json.loads() or a safe schema (marshmallow/pydantic). Never unpickle untrusted data.",
                cvss_score=10.0,
            ),
            GroundTruthIssue(
                file_path="services/webhook.py", line_no=12,
                category=IssueCategory.SECURITY, severity=Severity.CRITICAL,
                description="SSRF: requests.get(url) with no URL validation allows attacker to probe internal services (http://169.254.169.254/metadata, http://localhost:6379).",
                suggested_fix="Validate URL against allowlist of known-safe hosts; block private IP ranges.",
                cvss_score=8.8,
            ),
            GroundTruthIssue(
                file_path="services/webhook.py", line_no=16,
                category=IssueCategory.SECURITY, severity=Severity.ERROR,
                description="Timing attack: string equality `==` for API key comparison leaks key length/prefix via timing side-channel. Use constant-time comparison.",
                suggested_fix="import hmac; return hmac.compare_digest(provided, expected)",
                cvss_score=5.3,
            ),
            GroundTruthIssue(
                file_path="services/cache.py", line_no=16,
                category=IssueCategory.RACE_CONDITION, severity=Severity.WARNING,
                description="cache_invalidate checks `key in _cache` then `del _cache[key]` without holding the lock. Another thread can delete the key between check and delete (TOCTOU).",
                suggested_fix="with _lock: _cache.pop(key, None)",
            ),
        ],
        correct_verdict=Verdict.REJECT,
        explanation="RCE via pickle deserialization and SSRF are maximum-severity vulnerabilities. Immediate rejection required.",
    )
    return PullRequest(
        id="hard-002",
        title="feat: webhook processor with external resource fetching and caching",
        description="Processes incoming webhooks, fetches external data for integrations, adds an in-memory cache layer.",
        author="dev-hank",
        base_branch="main", head_branch="feat/webhook-processor",
        files=[file1, file2],
        ci_status=CIStatus(CIState.PASSING, [CICheck("tests", CIState.PASSING, "48 passed")]),
        test_summary=TestSummary(total=48, passed=48, coverage_pct=63.0),
        repo_context=RepoContext("integration-hub", "python", "Third-party integration hub",
                                 has_security_policy=True, contributors=8,
                                 coding_standards=["OWASP Top 10", "CWE/SANS Top 25"]),
        ground_truth=gt,
    )


def _hard_3() -> PullRequest:
    """Clean PR that should be approved — tests agent false-positive rate."""
    file1 = FileDiff(
        path="utils/retry.py", language="python",
        additions=28, deletions=0,
        lines=[
            DiffLine(1,  "import time, logging, functools", " "),
            DiffLine(2,  "from typing import Callable, Type, Tuple", " "),
            DiffLine(3,  "", " "),
            DiffLine(4,  "logger = logging.getLogger(__name__)", " "),
            DiffLine(5,  "", " "),
            DiffLine(6,  "def retry(", "+"),
            DiffLine(7,  "    max_attempts: int = 3,", "+"),
            DiffLine(8,  "    backoff_factor: float = 2.0,", "+"),
            DiffLine(9,  "    exceptions: Tuple[Type[Exception], ...] = (Exception,),", "+"),
            DiffLine(10, ") -> Callable:", "+"),
            DiffLine(11, '    """Exponential backoff retry decorator."""', "+"),
            DiffLine(12, "    def decorator(func):", "+"),
            DiffLine(13, "        @functools.wraps(func)", "+"),
            DiffLine(14, "        def wrapper(*args, **kwargs):", "+"),
            DiffLine(15, "            last_exc = None", "+"),
            DiffLine(16, "            for attempt in range(1, max_attempts + 1):", "+"),
            DiffLine(17, "                try:", "+"),
            DiffLine(18, "                    return func(*args, **kwargs)", "+"),
            DiffLine(19, "                except exceptions as e:", "+"),
            DiffLine(20, "                    last_exc = e", "+"),
            DiffLine(21, "                    if attempt < max_attempts:", "+"),
            DiffLine(22, "                        delay = backoff_factor ** (attempt - 1)", "+"),
            DiffLine(23, "                        logger.warning('Retry %d/%d after %.1fs: %s', attempt, max_attempts, delay, e)", "+"),
            DiffLine(24, "                        time.sleep(delay)", "+"),
            DiffLine(25, "            raise last_exc", "+"),
            DiffLine(26, "        return wrapper", "+"),
            DiffLine(27, "    return decorator", "+"),
        ]
    )
    gt = GroundTruth(
        issues=[],  # No issues — this is a correct PR
        correct_verdict=Verdict.APPROVE,
        explanation="Well-structured retry decorator with correct exponential backoff, proper logging, functools.wraps preservation, and typed signature. Approve.",
    )
    return PullRequest(
        id="hard-003",
        title="feat: exponential backoff retry decorator",
        description="Generic retry decorator with configurable attempts, backoff, and exception filtering.",
        author="dev-iris",
        base_branch="main", head_branch="feat/retry-decorator",
        files=[file1],
        ci_status=CIStatus(CIState.PASSING, [
            CICheck("tests", CIState.PASSING, "29 passed"),
            CICheck("mypy", CIState.PASSING, "No type errors"),
            CICheck("coverage", CIState.PASSING, "98% coverage"),
        ]),
        test_summary=TestSummary(total=29, passed=29, coverage_pct=98.0),
        repo_context=RepoContext("core-utils", "python", "Shared utility library",
                                 has_security_policy=False, stars=340, contributors=9),
        ground_truth=gt,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

EASY_PRS   = [_easy_1,   _easy_2,   _easy_3]
MEDIUM_PRS = [_medium_1, _medium_2, _medium_3]
HARD_PRS   = [_hard_1,   _hard_2,   _hard_3]

ALL_PRS = {
    "easy":   EASY_PRS,
    "medium": MEDIUM_PRS,
    "hard":   HARD_PRS,
}


def get_pr(difficulty: str, index: int) -> PullRequest:
    return ALL_PRS[difficulty][index % len(ALL_PRS[difficulty])]()


def all_prs() -> list[PullRequest]:
    return [fn() for difficulty in ALL_PRS.values() for fn in difficulty]
