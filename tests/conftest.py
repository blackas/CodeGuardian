"""Shared test fixtures for CodeGuardian."""

from typing import Any

import pytest


@pytest.fixture
def sample_single_hunk_patch() -> str:
    """Single hunk with 3 additions."""
    return (
        "@@ -10,4 +10,6 @@\n"
        " context_line\n"
        "+added_line_1\n"
        "+added_line_2\n"
        " context_line\n"
        " context_line\n"
        "+added_line_3"
    )


@pytest.fixture
def sample_multi_hunk_patch() -> str:
    """Two hunks in one file."""
    return "@@ -5,3 +5,4 @@\n ctx\n+new1\n ctx\n@@ -20,2 +21,3 @@\n ctx\n+new2\n+new3"


@pytest.fixture
def sample_delete_only_patch() -> str:
    """Only deletions, no additions."""
    return "@@ -10,3 +10,1 @@\n-deleted1\n-deleted2\n context"


@pytest.fixture
def sample_binary_file() -> dict[str, Any]:
    """Binary file dict with patch=None."""
    return {
        "filename": "assets/logo.png",
        "patch": None,
        "additions": 0,
        "deletions": 0,
    }


@pytest.fixture
def sample_mixed_files() -> list[dict[str, Any]]:
    """Mixed extensions: reviewable and non-reviewable files."""
    return [
        {
            "filename": "src/main.py",
            "patch": "@@ -1,2 +1,3 @@\n ctx\n+new",
            "additions": 1,
            "deletions": 0,
        },
        {
            "filename": "src/app.ts",
            "patch": "@@ -1,2 +1,3 @@\n ctx\n+new",
            "additions": 1,
            "deletions": 0,
        },
        {
            "filename": "src/index.js",
            "patch": "@@ -1,2 +1,3 @@\n ctx\n+new",
            "additions": 1,
            "deletions": 0,
        },
        {
            "filename": "template.html",
            "patch": "@@ -1,2 +1,3 @@\n ctx\n+new",
            "additions": 1,
            "deletions": 0,
        },
        {
            "filename": "README.md",
            "patch": "@@ -1,2 +1,3 @@\n ctx\n+new",
            "additions": 1,
            "deletions": 0,
        },
        {
            "filename": "data.csv",
            "patch": "@@ -1,2 +1,3 @@\n ctx\n+new",
            "additions": 1,
            "deletions": 0,
        },
        {
            "filename": "assets/logo.png",
            "patch": None,
            "additions": 0,
            "deletions": 0,
        },
        {
            "filename": "removed.py",
            "patch": "@@ -1,3 +0,0 @@\n-line1\n-line2\n-line3",
            "additions": 0,
            "deletions": 3,
        },
    ]


@pytest.fixture
def sample_event_payload() -> dict[str, Any]:
    """Mock GitHub webhook event payload."""
    return {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "number": 42,
            "title": "Add feature X",
            "body": "This PR adds feature X to the project.",
            "head": {"sha": "abc123def456"},
        },
        "repository": {
            "full_name": "owner/repo",
        },
    }


@pytest.fixture
def sample_ai_response() -> dict[str, Any]:
    """Mock OpenAI chat completion response."""
    return {
        "id": "chatcmpl-abc123",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        '{"comments": ['
                        '{"path": "src/main.py", "line": 15, '
                        '"body": "Consider using a context manager here."},'
                        '{"path": "src/main.py", "line": 23, '
                        '"body": "This variable name could be more descriptive."}'
                        "]}"
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 100,
            "total_tokens": 600,
        },
    }


@pytest.fixture
def sample_gitlab_mr_changes() -> dict[str, Any]:
    """Mock GitLab MR changes response with 2 files."""
    return {
        "changes": [
            {
                "new_path": "src/main.py",
                "diff": (
                    "@@ -1,3 +1,5 @@\n"
                    " context_line\n"
                    "+added_line_1\n"
                    "+added_line_2\n"
                    " context_end\n"
                ),
            },
            {
                "new_path": "src/utils.py",
                "diff": (
                    "@@ -10,2 +10,4 @@\n"
                    " existing_code\n"
                    "+new_helper_1\n"
                    "+new_helper_2\n"
                    " more_code\n"
                ),
            },
        ]
    }


@pytest.fixture
def sample_gitlab_diff_refs() -> dict[str, str]:
    """Mock mr.diff_refs with base/start/head SHA."""
    return {
        "base_sha": "base_sha_aaa111",
        "start_sha": "start_sha_bbb222",
        "head_sha": "head_sha_ccc333",
    }
