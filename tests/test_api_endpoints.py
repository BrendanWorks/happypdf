"""
API-surface tests for api/main.py upload guardrails and path-parameter hygiene.

These exercise only the rejection paths — nothing here starts a live pipeline
job or calls Modal/provider APIs.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "api"))

import main as api_main  # noqa: E402


@pytest.fixture
def client():
    return TestClient(api_main.app)


class TestUploadGuardrails:
    def test_rejects_non_pdf_extension(self, client):
        r = client.post("/api/jobs/live", files={"file": ("x.txt", b"hello", "text/plain")})
        assert r.status_code == 400

    def test_rejects_fake_pdf_content(self, client):
        """A .pdf name with non-PDF bytes is rejected before spending GPU time."""
        r = client.post(
            "/api/jobs/live", files={"file": ("x.pdf", b"MZ not a pdf", "application/pdf")}
        )
        assert r.status_code == 400
        assert "look like a PDF" in r.json()["detail"]

    def test_rejects_oversized_pdf(self, client, monkeypatch):
        monkeypatch.setattr(api_main, "MAX_UPLOAD_BYTES", 1024)
        big = b"%PDF-1.7" + b"\x00" * 2048
        r = client.post("/api/jobs/live", files={"file": ("big.pdf", big, "application/pdf")})
        assert r.status_code == 413

    def test_rate_limit_returns_429(self, client, monkeypatch):
        monkeypatch.setattr(api_main, "DAILY_LIMIT", 0)
        import fitz

        doc = fitz.open()
        doc.new_page()
        r = client.post(
            "/api/jobs/live", files={"file": ("x.pdf", doc.tobytes(), "application/pdf")}
        )
        assert r.status_code == 429

    def test_invalid_upload_does_not_consume_quota(self, client, monkeypatch):
        """Content sniffing runs before the rate check."""
        counted = []
        monkeypatch.setattr(
            api_main.RATE_LIMITER,
            "check_and_increment",
            lambda limit: counted.append(1) or (True, 1),
        )
        client.post("/api/jobs/live", files={"file": ("x.pdf", b"junk", "application/pdf")})
        assert counted == []


class TestPathParameterHygiene:
    def test_unknown_job_404(self, client):
        assert client.get("/api/jobs/ffffffffffff").status_code == 404

    def test_demo_name_traversal_rejected(self, client):
        # Encoded slashes / dots must never reach the snapshot path join.
        r = client.post("/api/jobs/demo/..%2F..%2Fsecrets")
        assert r.status_code == 404

    def test_manifest_bad_jid_404(self, client):
        r = client.get('/api/jobs/x"; rm -rf/manifest')
        assert r.status_code == 404

    def test_manifest_header_only_safe_ids(self, client):
        """Content-Disposition never carries an unvalidated path param."""
        # A known-good demo snapshot id (if snapshots are present in the repo)
        snap = ROOT / "api" / "snapshots" / "syllabus.json"
        if not snap.exists():
            pytest.skip("no demo snapshots in this checkout")
        r = client.get("/api/jobs/syllabus/manifest")
        assert r.status_code == 200
        assert r.headers["content-disposition"] == 'attachment; filename="syllabus_manifest.json"'


class TestDeepHealth:
    def test_disabled_locally_no_network(self, client, monkeypatch):
        """Outside Modal (and without the opt-in flag) health must not make
        provider/network calls — pytest and local dev stay offline."""
        monkeypatch.delenv("HAPPYPDF_ON_MODAL", raising=False)
        monkeypatch.delenv("HAPPYPDF_DEEP_HEALTH", raising=False)
        monkeypatch.setattr(
            api_main, "_run_deep_checks", lambda: (_ for _ in ()).throw(AssertionError)
        )
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["checks"] == {"deep_checks": "disabled"}

    def test_degraded_when_a_check_fails(self, client, monkeypatch):
        monkeypatch.setenv("HAPPYPDF_DEEP_HEALTH", "1")
        monkeypatch.setattr(
            api_main,
            "_run_deep_checks",
            lambda: {"anthropic_key": "ok", "openai_key": "invalid"},
        )
        monkeypatch.setitem(api_main._health_cache, "checked_at", 0.0)
        r = client.get("/api/health")
        assert r.json()["status"] == "degraded"
        assert r.json()["checks"]["openai_key"] == "invalid"

    def test_checks_are_cached(self, client, monkeypatch):
        monkeypatch.setenv("HAPPYPDF_DEEP_HEALTH", "1")
        calls = []
        monkeypatch.setattr(
            api_main, "_run_deep_checks", lambda: calls.append(1) or {"anthropic_key": "ok"}
        )
        monkeypatch.setitem(api_main._health_cache, "checked_at", 0.0)
        client.get("/api/health")
        client.get("/api/health")
        assert len(calls) == 1  # second request served from cache


class TestServedHtmlHeaders:
    def test_final_html_served_with_csp_sandbox(self, client):
        jid = api_main._new_job("live", "t.pdf")
        api_main._set(jid, final_html="<!DOCTYPE html><html><body>hi</body></html>")
        r = client.get(f"/api/jobs/{jid}/html")
        assert r.status_code == 200
        assert "sandbox" in r.headers.get("content-security-policy", "")
