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


WEBHOOK_SECRET = "test-webhook-secret"

PR_EVENT_PAYLOAD = {
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


@pytest.fixture
def client():
    with patch.dict("os.environ", {
        "GITHUB_TOKEN": "ghp_test",
        "WEBHOOK_SECRET": WEBHOOK_SECRET,
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
        response = client.post("/webhook", json={"action": "opened"})
        assert response.status_code == 403

    def test_rejects_invalid_signature(self, client):
        response = client.post(
            "/webhook",
            json={"action": "opened"},
            headers={"X-Hub-Signature-256": "sha256=invalid"},
        )
        assert response.status_code == 403


class TestWebhookEventHandling:
    def test_ignores_non_pr_events(self, client):
        payload = json.dumps({"action": "created"}).encode()
        sig = _make_signature(payload, WEBHOOK_SECRET)
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
    def test_processes_pr_opened(self, mock_run, client):
        payload = json.dumps(PR_EVENT_PAYLOAD).encode()
        sig = _make_signature(payload, WEBHOOK_SECRET)
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

    @patch("src.webhook_server.run_review")
    def test_ignores_pr_closed_action(self, mock_run, client):
        payload_dict = {**PR_EVENT_PAYLOAD, "action": "closed"}
        payload = json.dumps(payload_dict).encode()
        sig = _make_signature(payload, WEBHOOK_SECRET)
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
        assert response.json()["status"] == "ignored"
        mock_run.assert_not_called()
