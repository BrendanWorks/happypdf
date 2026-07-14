"""
Tests for the UX/latency work: stage timestamps, page counting, the HTML blob
store (job records must stay small for 1.5s polling), and the baseline-preview
endpoint.
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

from job_store import JobStore  # noqa: E402


@pytest.fixture
def client():
    return TestClient(api_main.app)


def _tiny_pdf(pages: int = 2) -> bytes:
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    return doc.tobytes()


class TestStageTimestamps:
    def test_stage_transition_stamps_stage_started(self):
        jid = api_main._new_job("live", "t.pdf")
        first = api_main.JOBS.get(jid)["stage_started"]
        time.sleep(0.01)
        api_main._set(jid, stage="extracting")
        after = api_main.JOBS.get(jid)["stage_started"]
        assert after > first

    def test_data_only_set_does_not_restamp(self):
        jid = api_main._new_job("live", "t.pdf")
        api_main._set(jid, stage="extracting")
        stamped = api_main.JOBS.get(jid)["stage_started"]
        api_main._set(jid, baseline={"score": 100})
        api_main._set(jid, stage="extracting")  # same stage — no restamp
        assert api_main.JOBS.get(jid)["stage_started"] == stamped


class TestPageCount:
    def test_valid_pdf_records_page_count(self, client, monkeypatch):
        # Prevent the worker thread from running the real pipeline.
        monkeypatch.setattr(api_main, "_live", lambda *a, **k: None)
        pdf = _tiny_pdf(pages=3)
        r = client.post("/api/jobs/live", files={"file": ("t.pdf", pdf, "application/pdf")})
        assert r.status_code == 200
        jid = r.json()["job_id"]
        status = client.get(f"/api/jobs/{jid}").json()
        assert status["page_count"] == 3

    def test_corrupt_pdf_rejected_before_gpu(self, client):
        r = client.post(
            "/api/jobs/live",
            files={"file": ("t.pdf", b"%PDF-1.7 this is not a real pdf body", "application/pdf")},
        )
        assert r.status_code == 400
        assert "couldn't be read" in r.json()["detail"]


class TestHtmlBlobStore:
    def test_put_get_blob(self):
        store = JobStore(on_modal=False)
        store.put_blob("abc123", "final_html", "<html>x</html>")
        assert store.get_blob("abc123", "final_html") == "<html>x</html>"
        assert store.get_blob("abc123", "baseline_html") is None

    def test_prune_honors_blob_timestamps(self):
        store = JobStore(on_modal=False)
        store.put_blob("fresh0000000", "final_html", "keep")
        store._mem["old000000000:final_html"] = {"updated": time.time() - 999999, "text": "drop"}
        removed = store.prune()
        assert removed == 1
        assert store.get_blob("fresh0000000", "final_html") == "keep"

    def test_job_record_stays_small(self):
        """The whole point: HTML must not ride along on every poll fetch."""
        jid = api_main._new_job("live", "t.pdf")
        api_main.JOBS.put_blob(jid, "final_html", "<html>" + "x" * 100000 + "</html>")
        api_main._set(jid, has_final_html=True)
        record = api_main.JOBS.get(jid)
        assert len(str(record)) < 5000


class TestHtmlVersions:
    def _job_with_blobs(self):
        jid = api_main._new_job("live", "t.pdf")
        api_main.JOBS.put_blob(
            jid, "baseline_html", "<!DOCTYPE html><html><body>base</body></html>"
        )
        api_main.JOBS.put_blob(jid, "final_html", "<!DOCTYPE html><html><body>final</body></html>")
        api_main._set(jid, has_baseline_html=True, has_final_html=True)
        return jid

    def test_final_default_and_baseline_param(self, client):
        jid = self._job_with_blobs()
        assert "final" in client.get(f"/api/jobs/{jid}/html").text
        assert "base" in client.get(f"/api/jobs/{jid}/html?version=baseline").text

    def test_invalid_version_404(self, client):
        jid = self._job_with_blobs()
        assert client.get(f"/api/jobs/{jid}/html?version=evil").status_code == 404

    def test_legacy_record_final_html_still_served(self, client):
        """Jobs created before the blob store keep HTML inline on the record."""
        jid = api_main._new_job("live", "t.pdf")
        api_main._set(jid, final_html="<!DOCTYPE html><html><body>legacy</body></html>")
        r = client.get(f"/api/jobs/{jid}/html")
        assert r.status_code == 200 and "legacy" in r.text
        # and the status endpoint reports has_html for it
        assert client.get(f"/api/jobs/{jid}").json()["has_html"] is True

    def test_status_never_leaks_blob_records(self, client):
        jid = self._job_with_blobs()
        # Blob keys share the store namespace; the status route must reject them.
        r = client.get(f"/api/jobs/{jid}:final_html")
        assert r.status_code == 404
        # And the job's own status carries flags, not HTML.
        body = client.get(f"/api/jobs/{jid}").json()
        assert body["has_baseline_html"] is True
        assert "final_html" not in body and "baseline_html" not in body


class TestWarmupHelper:
    def test_warm_ping_swallows_all_failures(self, monkeypatch):
        """The pre-warm is fire-and-forget: a dead URL must never raise."""
        monkeypatch.setenv("OLMO_REVIEWER_URL", "http://127.0.0.1:1")
        import reviewers

        monkeypatch.setattr(reviewers, "OLMO_URL", "http://127.0.0.1:1")
        api_main._warm_olmo_reviewer()  # must simply return
