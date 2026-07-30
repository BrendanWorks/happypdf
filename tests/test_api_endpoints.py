"""
API-surface tests for api/main.py upload guardrails and path-parameter hygiene.

These exercise only the rejection paths — nothing here starts a live pipeline
job or calls Modal/provider APIs.
"""

import sys
import time
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

    def test_failed_checks_use_short_ttl(self, client, monkeypatch):
        """A transient failure must be re-checked soon, not remembered for 24h
        (a cached blip re-alerted the monitor every 30 min on 2026-07-14)."""
        monkeypatch.setenv("HAPPYPDF_DEEP_HEALTH", "1")
        results = [{"google_key": "invalid"}, {"google_key": "ok"}]
        monkeypatch.setattr(api_main, "_run_deep_checks", lambda: results.pop(0))
        monkeypatch.setitem(api_main._health_cache, "checked_at", 0.0)
        assert client.get("/api/health").json()["status"] == "degraded"
        # Simulate the failure sitting in cache longer than the fail-TTL but
        # far less than the 24h success-TTL.
        monkeypatch.setitem(
            api_main._health_cache, "checked_at", time.time() - api_main.HEALTH_FAIL_TTL_S - 1
        )
        assert client.get("/api/health").json()["status"] == "ok"  # re-checked


class TestServedHtmlHeaders:
    def test_final_html_served_with_csp_sandbox(self, client):
        jid = api_main._new_job("live", "t.pdf")
        api_main._set(jid, final_html="<!DOCTYPE html><html><body>hi</body></html>")
        r = client.get(f"/api/jobs/{jid}/html")
        assert r.status_code == 200
        assert "sandbox" in r.headers.get("content-security-policy", "")


class TestReplayReportBlocks:
    """Demo replays must surface the same report blocks a live run produces
    (PointCheck coverage, alt-text judge, fidelity gate) — and must still
    complete on older snapshots captured before those blocks existed."""

    SNAP_CORE = {
        "source": "test snapshot",
        "baseline": {"passes": 10, "violations": 0, "score": 100},
        "rounds": [
            {
                "round": 1,
                "patches_applied": 2,
                "passes": 12,
                "score": 100,
                "violations": 0,
                "gate_passed": True,
                "gate_checks": [],
            }
        ],
        "final": {"passes": 12, "violations": 0, "score": 100},
        "final_html": "<html></html>",
        "enhancements": [],
        "stopped_reason": "converged",
        "total_seconds": 123.0,
    }

    def _run_replay(self, monkeypatch, snap):
        monkeypatch.setattr(api_main, "_load_snapshot", lambda name: snap)
        monkeypatch.setattr(api_main.time, "sleep", lambda s: None)
        jid = api_main._new_job("replay", "test")
        api_main._replay(jid, "test")
        return api_main.JOBS.get(jid)

    def test_blocks_pass_through(self, monkeypatch):
        snap = {
            **self.SNAP_CORE,
            "pointcheck_baseline": {"findings": [], "counts": {}},
            "pointcheck": {"findings": [{"sc": "1.1.1"}], "counts": {"1.1.1": 1}},
            "alt_text_review": {"images_judged": 3, "flagged_low_quality": []},
            "fidelity": {"status": "ok", "findings": [], "pages_analyzed": 2},
            "reviewer_health": {"olmo": "ok"},
        }
        rec = self._run_replay(monkeypatch, snap)
        assert rec["status"] == "done"
        assert rec["pointcheck_baseline"] == {"findings": [], "counts": {}}
        assert rec["pointcheck"]["counts"] == {"1.1.1": 1}
        assert rec["alt_text_review"]["images_judged"] == 3
        assert rec["fidelity"]["status"] == "ok"
        assert rec["reviewer_health"] == {"olmo": "ok"}

    def test_old_snapshot_without_blocks_still_completes(self, monkeypatch):
        rec = self._run_replay(monkeypatch, dict(self.SNAP_CORE))
        assert rec["status"] == "done"
        assert rec.get("pointcheck") is None
        assert rec.get("alt_text_review") is None
        assert rec.get("fidelity") is None


class TestAccessTokenQuotas:
    """An issued token draws on its own daily bucket so a pilot partner cannot
    exhaust the public pool (and vice versa)."""

    TOKENS = {"tok-ct-secret": {"label": "community-transit", "daily_limit": 3}}

    @pytest.fixture
    def tokened(self, monkeypatch):
        monkeypatch.setattr(api_main, "_ACCESS_TOKENS", self.TOKENS)
        monkeypatch.setattr(api_main, "DAILY_LIMIT", 2)
        api_main.RATE_LIMITER._mem.clear()
        return api_main

    def _pdf(self):
        import fitz

        doc = fitz.open()
        doc.new_page()
        return doc.tobytes()

    def _post(self, client, token=None, header=True):
        files = {"file": ("x.pdf", self._pdf(), "application/pdf")}
        if token and header:
            return client.post("/api/jobs/live", files=files, headers={"X-HappyPDF-Token": token})
        if token:
            return client.post("/api/jobs/live", files=files, data={"access_token": token})
        return client.post("/api/jobs/live", files=files)

    def test_token_bucket_is_separate_from_public_pool(self, client, tokened, monkeypatch):
        # Drain the public pool (limit 2), then the token must still work.
        monkeypatch.setattr(api_main, "_live", lambda *a, **k: None)
        assert self._post(client).status_code == 200
        assert self._post(client).status_code == 200
        assert self._post(client).status_code == 429  # public exhausted
        r = self._post(client, "tok-ct-secret")
        assert r.status_code == 200, "token should not be blocked by the public pool"

    def test_token_quota_is_enforced(self, client, tokened, monkeypatch):
        monkeypatch.setattr(api_main, "_live", lambda *a, **k: None)
        for _ in range(3):  # token daily_limit = 3
            assert self._post(client, "tok-ct-secret").status_code == 200
        r = self._post(client, "tok-ct-secret")
        assert r.status_code == 429
        assert "access token" in r.json()["detail"]
        # ...and the public pool is untouched by the token's spending.
        assert self._post(client).status_code == 200

    def test_token_accepted_as_form_field_too(self, client, tokened, monkeypatch):
        monkeypatch.setattr(api_main, "_live", lambda *a, **k: None)
        assert self._post(client, "tok-ct-secret", header=False).status_code == 200

    def test_invalid_token_rejected(self, client, tokened):
        r = self._post(client, "not-a-real-token")
        assert r.status_code == 401

    def test_invalid_token_does_not_consume_quota(self, client, tokened):
        self._post(client, "not-a-real-token")
        assert api_main.RATE_LIMITER._mem == {}

    def test_token_does_not_bypass_upload_guardrails(self, client, tokened, monkeypatch):
        """A quota raises the ceiling; it must not skip content sniffing."""
        r = client.post(
            "/api/jobs/live",
            files={"file": ("x.pdf", b"MZ not a pdf", "application/pdf")},
            headers={"X-HappyPDF-Token": "tok-ct-secret"},
        )
        assert r.status_code == 400

    def test_no_tokens_configured_means_public_only(self, client, monkeypatch):
        monkeypatch.setattr(api_main, "_ACCESS_TOKENS", {})
        r = self._post(client, "anything")
        assert r.status_code == 401


class TestAccessTokenConfigParsing:
    def _parse(self, monkeypatch, raw):
        monkeypatch.setattr(api_main, "_ACCESS_TOKENS", None)
        monkeypatch.setenv("HAPPYPDF_ACCESS_TOKENS", raw)
        return api_main._access_tokens()

    def test_absent_config_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(api_main, "_ACCESS_TOKENS", None)
        monkeypatch.delenv("HAPPYPDF_ACCESS_TOKENS", raising=False)
        assert api_main._access_tokens() == {}

    def test_malformed_json_degrades_to_public_only(self, monkeypatch):
        assert self._parse(monkeypatch, "{not json") == {}

    def test_entries_with_unsafe_labels_are_dropped(self, monkeypatch):
        """The label becomes a store key, so it must stay a slug."""
        raw = '{"t": {"label": "../../etc", "daily_limit": 5}}'
        assert self._parse(monkeypatch, raw) == {}

    def test_entries_with_bad_quota_are_dropped(self, monkeypatch):
        assert self._parse(monkeypatch, '{"t": {"label": "ok", "daily_limit": "lots"}}') == {}
        assert self._parse(monkeypatch, '{"t": {"label": "ok", "daily_limit": 0}}') == {}

    def test_valid_entry_loads(self, monkeypatch):
        got = self._parse(monkeypatch, '{"t": {"label": "ct-pilot", "daily_limit": 200}}')
        assert got == {"t": {"label": "ct-pilot", "daily_limit": 200}}
