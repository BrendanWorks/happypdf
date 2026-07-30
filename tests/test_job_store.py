"""
Tests for the persistent job store (src/job_store.py).

These cover the in-process fallback path (no Modal required) and the
interrupted-if-stale logic that turns a job whose worker died on a container
recycle into a clean terminal error instead of a forever-"running" record.
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from job_store import (  # noqa: E402
    STALE_RUNNING_S,
    DailyRateLimiter,
    JobStore,
    mark_interrupted_if_stale,
)


class TestJobStore:
    """In-process JobStore behaves like the dict it replaces."""

    def test_put_get_contains(self):
        store = JobStore(on_modal=False)
        assert "abc" not in store
        assert store.get("abc") is None
        store.put("abc", {"status": "running", "updated": time.time()})
        assert "abc" in store
        assert store.get("abc")["status"] == "running"
        assert len(store) == 1

    def test_put_replaces_whole_record(self):
        """put writes the whole record back (modal.Dict returns copies)."""
        store = JobStore(on_modal=False)
        store.put("j", {"status": "running", "stage": "uploading", "updated": time.time()})
        rec = store.get("j")
        rec["stage"] = "extracting"
        store.put("j", rec)
        assert store.get("j")["stage"] == "extracting"

    def test_prune_removes_only_old_records(self):
        store = JobStore(on_modal=False)
        now = time.time()
        store.put("fresh", {"status": "done", "updated": now})
        store.put("old", {"status": "done", "updated": now - 10_000})
        removed = store.prune(ttl_s=3600)
        assert removed == 1
        assert "fresh" in store
        assert "old" not in store

    def test_prune_falls_back_to_started_timestamp(self):
        store = JobStore(on_modal=False)
        store.put("old", {"status": "done", "started": time.time() - 10_000})
        assert store.prune(ttl_s=3600) == 1


class TestMarkInterruptedIfStale:
    """A job stuck at 'running' after a recycle becomes a terminal error."""

    def test_fresh_running_job_unchanged(self):
        job = {"status": "running", "stage": "round2", "updated": time.time()}
        assert mark_interrupted_if_stale(job) is job

    def test_stale_running_job_becomes_error(self):
        job = {
            "status": "running",
            "stage": "round2",
            "updated": time.time() - STALE_RUNNING_S - 10,
        }
        out = mark_interrupted_if_stale(job)
        assert out["status"] == "error"
        assert out["stage"] == "error"
        assert "interrupted" in out["error"].lower()
        # original is not mutated
        assert job["status"] == "running"

    def test_done_job_never_flipped(self):
        job = {"status": "done", "updated": time.time() - 100_000}
        assert mark_interrupted_if_stale(job) is job

    def test_none_is_passed_through(self):
        assert mark_interrupted_if_stale(None) is None

    def test_falls_back_to_started_when_no_updated(self):
        job = {"status": "running", "started": time.time() - STALE_RUNNING_S - 10}
        assert mark_interrupted_if_stale(job)["status"] == "error"


class TestDailyRateLimiterBuckets:
    """Buckets let an issued token spend its own quota. The store key is
    "<date>:<bucket>", which the day-prune must still age out correctly."""

    def test_buckets_count_independently(self):
        rl = DailyRateLimiter(on_modal=False)
        assert rl.check_and_increment(1) == (True, 1)
        assert rl.check_and_increment(1) == (False, 1)  # public pool spent
        # A bucketed caller is unaffected by the public pool being empty.
        assert rl.check_and_increment(2, bucket="ct") == (True, 1)
        assert rl.check_and_increment(2, bucket="ct") == (True, 2)
        assert rl.check_and_increment(2, bucket="ct") == (False, 2)
        # Two different tokens do not share a bucket.
        assert rl.check_and_increment(1, bucket="other") == (True, 1)

    def test_bucket_never_stores_the_token_itself(self):
        rl = DailyRateLimiter(on_modal=False)
        rl.check_and_increment(5, bucket="ct-pilot")
        assert all("ct-pilot" in k for k in rl._mem)
        assert not any("secret" in k for k in rl._mem)

    def test_prune_ages_out_bucketed_keys_but_keeps_today(self):
        from datetime import datetime

        rl = DailyRateLimiter(on_modal=False)
        today = datetime.now().strftime("%Y-%m-%d")
        rl._mem["2020-01-01"] = 9
        rl._mem["2020-01-01:ct"] = 9
        rl.check_and_increment(5, bucket="ct")   # writes today:ct and prunes
        rl.check_and_increment(5)                # writes today and prunes
        assert "2020-01-01" not in rl._mem
        assert "2020-01-01:ct" not in rl._mem
        assert rl._mem[f"{today}:ct"] == 1
        assert rl._mem[today] == 1
