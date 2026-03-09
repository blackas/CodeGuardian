# Self-Hosted CodeGuardian with Codex OAuth + Webhook

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run CodeGuardian on a personal MacBook using Codex CLI (ChatGPT Plus OAuth) instead of OpenAI Platform API, triggered by GitHub webhooks.

**Architecture:** A lightweight FastAPI webhook server runs on the MacBook, receiving GitHub PR events via a tunnel (ngrok/Cloudflare). When a PR is opened/updated, it calls `codex exec` with a structured output schema to perform the review, then posts comments back via the existing GitHub client.

**Tech Stack:** FastAPI, uvicorn, Codex CLI (`codex exec --output-schema`), ngrok/cloudflare tunnel, existing PyGithub integration.

---

### Task 1: Add FastAPI + uvicorn dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add dependencies**

Add `fastapi` and `uvicorn` to the project dependencies in `pyproject.toml`:

```toml
dependencies = [
    "PyGithub>=2.5.0",
    "python-gitlab>=4.13.0",
    "openai>=1.58.0",
    "pydantic>=2.10.0",
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
]
```

**Step 2: Install dependencies**

Run: `uv sync`

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add fastapi and uvicorn dependencies for webhook server"
```

---

### Task 2: Create Codex structured output schema

**Files:**
- Create: `src/review_schema.json`

**Step 1: Write the JSON schema**

This schema matches the existing `ReviewResponse` Pydantic model so `codex exec --output-schema` returns parseable structured output:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "comments": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "file_path": { "type": "string" },
          "line_number": { "type": "integer" },
          "severity": { "type": "string", "enum": ["error", "warning", "info"] },
          "category": { "type": "string", "enum": ["bug", "security", "performance", "readability"] },
          "comment": { "type": "string" }
        },
        "required": ["file_path", "line_number", "severity", "category", "comment"],
        "additionalProperties": false
      }
    },
    "summary": { "type": "string" }
  },
  "required": ["comments", "summary"],
  "additionalProperties": false
}
```

**Step 2: Commit**

```bash
git add src/review_schema.json
git commit -m "feat: add Codex structured output schema for code review"
```

---

### Task 3: Create CodexReviewer as alternative to AIReviewer

**Files:**
- Create: `src/codex_reviewer.py`
- Create: `tests/test_codex_reviewer.py`

**Step 1: Write the failing tests**

```python
# tests/test_codex_reviewer.py
"""Tests for Codex CLI-based code reviewer."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.ai_reviewer import ReviewComment, ReviewResponse
from src.codex_reviewer import CodexReviewer


class TestCodexReviewerBuildPrompt:
    """Test prompt construction for codex exec."""

    def test_builds_prompt_with_file_info(self):
        reviewer = CodexReviewer()
        prompt = reviewer._build_prompt(
            file_path="src/app.py",
            patch="@@ -1 +1 @@\n-old\n+new",
            pr_title="Fix bug",
            pr_description="Fixes issue #1",
        )
        assert "src/app.py" in prompt
        assert "Fix bug" in prompt
        assert "@@ -1 +1 @@" in prompt

    def test_builds_prompt_with_project_context(self):
        reviewer = CodexReviewer(project_context="Django REST API")
        prompt = reviewer._build_prompt(
            file_path="src/app.py",
            patch="diff",
            pr_title="Test",
            pr_description="Test",
        )
        assert "Django REST API" in prompt


class TestCodexReviewerCallCodex:
    """Test codex exec subprocess invocation."""

    @patch("src.codex_reviewer.subprocess.run")
    def test_calls_codex_exec_and_parses_output(self, mock_run):
        review_data = {
            "comments": [
                {
                    "file_path": "src/app.py",
                    "line_number": 10,
                    "severity": "warning",
                    "category": "bug",
                    "comment": "Potential issue.",
                }
            ],
            "summary": "Found 1 issue.",
        }
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(review_data),
            stderr="",
        )

        reviewer = CodexReviewer()
        result = reviewer.review_diff(
            file_path="src/app.py",
            patch="@@ -1 +1 @@\n-old\n+new",
            pr_title="Fix bug",
            pr_description="Fixes #1",
        )

        assert isinstance(result, ReviewResponse)
        assert len(result.comments) == 1
        assert result.comments[0].severity == "warning"
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "codex" in cmd[0]
        assert "exec" in cmd

    @patch("src.codex_reviewer.subprocess.run")
    def test_returns_empty_on_codex_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: something went wrong",
        )

        reviewer = CodexReviewer()
        result = reviewer.review_diff(
            file_path="src/app.py",
            patch="diff",
            pr_title="Test",
            pr_description="Test",
        )

        assert isinstance(result, ReviewResponse)
        assert result.comments == []
        assert "Error" in result.summary


class TestCodexReviewerReviewFiles:
    """Test multi-file review aggregation."""

    @patch("src.codex_reviewer.subprocess.run")
    def test_aggregates_comments_from_multiple_files(self, mock_run):
        review_a = json.dumps({
            "comments": [{"file_path": "a.py", "line_number": 1, "severity": "error", "category": "bug", "comment": "Issue"}],
            "summary": "Review a",
        })
        review_b = json.dumps({
            "comments": [{"file_path": "b.py", "line_number": 5, "severity": "info", "category": "readability", "comment": "Note"}],
            "summary": "Review b",
        })
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=review_a, stderr=""),
            MagicMock(returncode=0, stdout=review_b, stderr=""),
        ]

        reviewer = CodexReviewer()
        comments = reviewer.review_files(
            files=[
                {"file_path": "a.py", "patch": "diff a"},
                {"file_path": "b.py", "patch": "diff b"},
            ],
            pr_title="Multi",
            pr_description="Test",
        )

        assert len(comments) == 2
        assert comments[0].file_path == "a.py"
        assert comments[1].file_path == "b.py"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_codex_reviewer.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'src.codex_reviewer')

**Step 3: Write the implementation**

```python
# src/codex_reviewer.py
"""Code reviewer using Codex CLI with structured output."""

import json
import logging
import os
import subprocess
from pathlib import Path

from src.ai_reviewer import ReviewComment, ReviewResponse

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "review_schema.json"


class CodexReviewer:
    """Code reviewer powered by Codex CLI (ChatGPT Plus OAuth).

    Uses `codex exec --output-schema` for structured review output.
    Requires Codex CLI installed and authenticated (`codex login`).
    """

    def __init__(self, project_context: str = "") -> None:
        self._project_context = project_context
        self._rate_limit_failure_count = 0

    def review_diff(
        self,
        file_path: str,
        patch: str,
        pr_title: str,
        pr_description: str,
    ) -> ReviewResponse:
        prompt = self._build_prompt(file_path, patch, pr_title, pr_description)
        return self._call_codex(prompt)

    def review_files(
        self,
        files: list[dict[str, str]],
        pr_title: str,
        pr_description: str,
    ) -> list[ReviewComment]:
        all_comments: list[ReviewComment] = []
        for file_info in files:
            response = self.review_diff(
                file_path=file_info["file_path"],
                patch=file_info["patch"],
                pr_title=pr_title,
                pr_description=pr_description,
            )
            all_comments.extend(response.comments)
        return all_comments

    def _build_prompt(
        self,
        file_path: str,
        patch: str,
        pr_title: str,
        pr_description: str,
    ) -> str:
        context_section = ""
        if self._project_context:
            context_section = (
                f"Project context:\n{self._project_context}\n\n"
            )

        return (
            f"You are a senior code reviewer. Review the following code diff and return structured JSON feedback.\n\n"
            f"{context_section}"
            f"Focus on: logic errors, security vulnerabilities, performance issues, readability.\n\n"
            f"File: {file_path}\n"
            f"PR Title: {pr_title}\n"
            f"PR Description: {pr_description}\n\n"
            f"Diff:\n```\n{patch}\n```\n\n"
            f"Return JSON with 'comments' array and 'summary' string."
        )

    def _call_codex(self, prompt: str) -> ReviewResponse:
        try:
            result = subprocess.run(
                [
                    "codex", "exec", prompt,
                    "--output-schema", str(SCHEMA_PATH),
                    "-o", "/dev/stdout",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                logger.error("Codex exec failed: %s", result.stderr)
                return ReviewResponse(
                    comments=[],
                    summary=f"Error: Codex exec failed: {result.stderr[:200]}",
                )

            parsed = json.loads(result.stdout)
            return ReviewResponse.model_validate(parsed)

        except subprocess.TimeoutExpired:
            logger.error("Codex exec timed out")
            return ReviewResponse(
                comments=[],
                summary="Error: Codex exec timed out after 120 seconds.",
            )
        except (json.JSONDecodeError, Exception) as e:
            logger.error("Failed to parse Codex output: %s", e)
            return ReviewResponse(
                comments=[],
                summary=f"Error: Failed to parse Codex output: {e}",
            )

    @property
    def rate_limit_failure_count(self) -> int:
        return self._rate_limit_failure_count
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_codex_reviewer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/codex_reviewer.py tests/test_codex_reviewer.py
git commit -m "feat: add CodexReviewer using codex exec with structured output"
```

---

### Task 4: Create webhook server

**Files:**
- Create: `src/webhook_server.py`
- Create: `tests/test_webhook_server.py`

**Step 1: Write the failing tests**

```python
# tests/test_webhook_server.py
"""Tests for webhook server."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_signature(payload: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


@pytest.fixture
def webhook_secret():
    return "test-webhook-secret"


@pytest.fixture
def client(webhook_secret):
    with patch.dict("os.environ", {
        "GITHUB_TOKEN": "ghp_test",
        "WEBHOOK_SECRET": webhook_secret,
    }):
        from src.webhook_server import app
        yield TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestWebhookSignatureValidation:
    def test_rejects_missing_signature(self, client):
        response = client.post(
            "/webhook",
            json={"action": "opened"},
        )
        assert response.status_code == 403

    def test_rejects_invalid_signature(self, client):
        response = client.post(
            "/webhook",
            json={"action": "opened"},
            headers={"X-Hub-Signature-256": "sha256=invalid"},
        )
        assert response.status_code == 403


class TestWebhookPREvents:
    def test_ignores_non_pr_events(self, client, webhook_secret):
        payload = json.dumps({"action": "created"}).encode()
        sig = _make_signature(payload, webhook_secret)
        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    @patch("src.webhook_server.run_review")
    def test_processes_pr_opened_event(self, mock_run, client, webhook_secret):
        payload_dict = {
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Test PR",
                "body": "Description",
                "head": {
                    "sha": "abc123",
                    "ref": "feature",
                    "repo": {"full_name": "owner/repo"},
                },
                "base": {
                    "ref": "main",
                    "repo": {"full_name": "owner/repo"},
                },
            },
            "repository": {"full_name": "owner/repo"},
        }
        payload = json.dumps(payload_dict).encode()
        sig = _make_signature(payload, webhook_secret)
        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "processing"
        mock_run.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_webhook_server.py -v`
Expected: FAIL

**Step 3: Write the implementation**

```python
# src/webhook_server.py
"""GitHub webhook server for self-hosted CodeGuardian reviews."""

import hashlib
import hmac
import logging
import os
import threading

from fastapi import FastAPI, Header, HTTPException, Request

from src.ai_reviewer import ReviewComment
from src.codex_reviewer import CodexReviewer
from src.diff_parser import filter_reviewable_files, get_valid_comment_lines
from src.github_client import GitHubClient
from src.review import build_summary, format_comment_body, validate_comment_lines

logger = logging.getLogger(__name__)

app = FastAPI(title="CodeGuardian Webhook Server")


def _verify_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def run_review(event_data: dict) -> None:
    """Run the CodeGuardian review pipeline for a PR event."""
    try:
        token = os.environ["GITHUB_TOKEN"]
        repo_name = event_data["repository"]["full_name"]

        platform = GitHubClient(
            token=token, repo_name=repo_name, event_data=event_data
        )
        context = platform.get_context()

        # Fetch project context
        agents_content = platform.get_file_content("AGENTS.md")
        project_context = agents_content if agents_content and agents_content.strip() else ""

        # Fork check
        if platform.is_fork():
            logger.warning("PR is from a fork. Skipping review.")
            return

        # Get and filter files
        raw_files = platform.get_files()
        file_dicts = [
            {
                "filename": f.filename,
                "patch": f.patch,
                "additions": f.additions,
                "deletions": f.deletions,
            }
            for f in raw_files
        ]
        reviewable = filter_reviewable_files(file_dicts)

        if not reviewable:
            platform.post_error_comment("No reviewable files found in this PR.")
            return

        # Use CodexReviewer instead of AIReviewer
        reviewer = CodexReviewer(project_context=project_context)

        review_files = [
            {"file_path": f["filename"], "patch": f["patch"]} for f in reviewable
        ]
        ai_comments = reviewer.review_files(
            files=review_files,
            pr_title=context.title,
            pr_description=context.description,
        )

        # Validate and post
        file_patches = {f["filename"]: f["patch"] for f in reviewable}
        valid_comments = validate_comment_lines(ai_comments, file_patches)

        platform_comments = [
            {
                "path": c.file_path,
                "body": format_comment_body(c),
                "line": c.line_number,
            }
            for c in valid_comments
        ]

        summary = build_summary(valid_comments)
        platform.post_review_comments(platform_comments, summary)

    except Exception as e:
        logger.exception("Review failed for PR")
        try:
            token = os.environ.get("GITHUB_TOKEN", "")
            repo_name = event_data.get("repository", {}).get("full_name", "")
            if token and repo_name:
                platform = GitHubClient(
                    token=token, repo_name=repo_name, event_data=event_data
                )
                platform.post_error_comment(f"CodeGuardian error: {e}")
        except Exception:
            logger.exception("Failed to post error comment")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    secret = os.environ.get("WEBHOOK_SECRET", "")
    payload = await request.body()

    if not _verify_signature(payload, x_hub_signature_256, secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored"}

    event_data = await request.json()
    action = event_data.get("action", "")

    if action not in ("opened", "synchronize"):
        return {"status": "ignored", "action": action}

    # Run review in background thread
    thread = threading.Thread(target=run_review, args=(event_data,), daemon=True)
    thread.start()

    pr_number = event_data.get("pull_request", {}).get("number")
    return {"status": "processing", "pr_number": pr_number}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_webhook_server.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/webhook_server.py tests/test_webhook_server.py
git commit -m "feat: add webhook server for self-hosted GitHub PR reviews"
```

---

### Task 5: Add server entry point

**Files:**
- Create: `src/server.py`

**Step 1: Write server entry point**

```python
# src/server.py
"""Entry point for the webhook server: python -m src.server"""

import uvicorn

from src.webhook_server import app


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
```

**Step 2: Test it starts**

Run: `timeout 3 uv run python -m src.server || true`
Expected: Uvicorn starts listening on 0.0.0.0:8000 (then exits from timeout)

**Step 3: Commit**

```bash
git add src/server.py
git commit -m "feat: add server entry point for webhook mode"
```

---

### Task 6: Verify existing tests still pass

**Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: All existing tests PASS. New tests PASS.

**Step 2: Commit if any fixups needed**

---

### Task 7: Update README with self-hosted usage

**Files:**
- Modify: `README.md`

**Step 1: Add Self-Hosted section to README**

Add a section after the existing setup instructions:

```markdown
## Self-Hosted Mode (Codex OAuth)

Run CodeGuardian on your own machine using Codex CLI with ChatGPT Plus — no OpenAI API key required.

### Prerequisites

- [Codex CLI](https://developers.openai.com/codex/cli/) installed and logged in (`codex login`)
- ChatGPT Plus/Pro subscription
- [ngrok](https://ngrok.com/) or Cloudflare Tunnel for HTTPS

### Setup

1. Clone and install:
   ```bash
   git clone https://github.com/your-org/CodeGuardian.git
   cd CodeGuardian
   uv sync
   ```

2. Set environment variables:
   ```bash
   export GITHUB_TOKEN="ghp_your_token"
   export WEBHOOK_SECRET="your_webhook_secret"
   ```

3. Start the server:
   ```bash
   uv run python -m src.server
   ```

4. Expose via tunnel:
   ```bash
   ngrok http 8000
   ```

5. Register webhook in GitHub repo Settings > Webhooks:
   - URL: `https://your-ngrok-url/webhook`
   - Content type: `application/json`
   - Secret: same as `WEBHOOK_SECRET`
   - Events: Pull requests
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add self-hosted mode setup instructions"
```
