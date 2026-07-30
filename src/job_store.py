"""Persistent job store for the demo API.

The API runs as a single Modal container that scales to zero. Job state used to
live in a plain in-process dict, so any container recycle (idle scaledown,
container lifetime, or a deploy) dropped every job and clients polling
GET /api/jobs/{id} got a 404.

This backs the job store with a `modal.Dict` when running on Modal (survives
recycles), and falls back to a plain in-process dict for local dev and tests so
nothing extra is required to run `uvicorn`/`pytest`. The public surface is the
few operations api/main.py needs: get / put / `in` / prune.
"""

import os
import threading
import time
from datetime import datetime

# Prune records older than this on job creation (keeps the Dict bounded).
JOB_TTL_S = 24 * 3600
# A job still marked "running" but untouched for longer than this had its worker
# thread killed by a container recycle; treat it as interrupted rather than
# leaving it "running" forever. Longer than any real pipeline stage.
STALE_RUNNING_S = 300
INTERRUPTED_MSG = "This conversion was interrupted (the server restarted). Please try again."


class JobStore:
    """job_id -> record, backed by a modal.Dict on Modal or an in-process dict.

    Values are always replaced whole (`put`) rather than mutated in place, because
    a modal.Dict returns copies — the caller must write the modified record back.
    """

    def __init__(self, on_modal: bool | None = None, name: str | None = None):
        if on_modal is None:
            on_modal = os.environ.get("HAPPYPDF_ON_MODAL") == "1"
        self._on_modal = on_modal
        # Staging deploys point at their own Dict via HAPPYPDF_JOBS_DICT so they
        # never touch production job state.
        self._name = name or os.environ.get("HAPPYPDF_JOBS_DICT", "happypdf-jobs")
        self._mem: dict[str, dict] = {}
        self._dict = None  # lazily created modal.Dict handle

    @property
    def _backend(self):
        if not self._on_modal:
            return self._mem
        if self._dict is None:
            # Imported lazily and created on first use (not at module import) so a
            # transient Modal hiccup can't crash-loop the container at startup.
            import modal

            self._dict = modal.Dict.from_name(self._name, create_if_missing=True)
        return self._dict

    def get(self, jid: str) -> dict | None:
        return self._backend.get(jid)

    def put(self, jid: str, record: dict) -> None:
        self._backend[jid] = record

    def __contains__(self, jid: str) -> bool:
        return jid in self._backend

    def __len__(self) -> int:
        backend = self._backend
        try:
            return len(backend)
        except TypeError:
            # modal.Dict may expose a .len() method instead of __len__.
            try:
                return backend.len()
            except Exception:
                return 0
        except Exception:
            return 0

    def put_blob(self, jid: str, name: str, text: str) -> None:
        """Store a large text blob (e.g. generated HTML) under its own key.

        Job records are fetched whole on every poll (~1.5s interval per
        client), so multi-MB HTML must not live inside them. Blob records
        carry their own `updated` timestamp so prune() ages them out with the
        same TTL as jobs."""
        self._backend[f"{jid}:{name}"] = {"updated": time.time(), "text": text}

    def get_blob(self, jid: str, name: str) -> str | None:
        rec = self._backend.get(f"{jid}:{name}")
        return rec.get("text") if isinstance(rec, dict) else None

    def prune(self, ttl_s: float = JOB_TTL_S) -> int:
        """Delete records last updated more than ttl_s ago. Returns count removed."""
        cutoff = time.time() - ttl_s
        backend = self._backend
        try:
            items = list(backend.items())
        except Exception:
            return 0
        removed = 0
        for k, v in items:
            ts = (v or {}).get("updated") or (v or {}).get("started") or 0
            if ts < cutoff:
                try:
                    del backend[k]
                    removed += 1
                except Exception:
                    pass
        return removed


class DailyRateLimiter:
    """Persistent daily counter for the paid live path.

    Backed by a modal.Dict on Modal so a container recycle can't reset the
    day's count to zero (the old in-process counter did exactly that), with an
    in-memory fallback for local dev/tests. Thread-safe within one process,
    which is sufficient because the API is pinned to max_containers=1.
    """

    def __init__(self, on_modal: bool | None = None, name: str | None = None):
        if on_modal is None:
            on_modal = os.environ.get("HAPPYPDF_ON_MODAL") == "1"
        self._on_modal = on_modal
        self._name = name or os.environ.get("HAPPYPDF_RATE_DICT", "happypdf-rate-limit")
        self._mem: dict[str, int] = {}
        self._dict = None
        self._lock = threading.Lock()

    @property
    def _backend(self):
        if not self._on_modal:
            return self._mem
        if self._dict is None:
            import modal

            self._dict = modal.Dict.from_name(self._name, create_if_missing=True)
        return self._dict

    def check_and_increment(self, limit: int, bucket: str = "") -> tuple[bool, int]:
        """Returns (allowed, count_after). Increments only when allowed.

        `bucket` partitions the counter so an issued access token draws on its
        own daily quota instead of the shared public pool. Keys are
        "<date>:<bucket>", which keeps the prune below correct: same-day token
        keys sort after the bare date, older ones sort before it.

        The bucket is a caller-supplied label (never the token itself), so no
        credential is written to the store.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        key = f"{today}:{bucket}" if bucket else today
        with self._lock:
            try:
                count = int(self._backend.get(key) or 0)
            except Exception:
                count = 0  # a transient store hiccup must not block conversions
            if count >= limit:
                return False, count
            count += 1
            try:
                self._backend[key] = count
                # Drop old days so the store stays a handful of keys.
                yesterday_and_older = [
                    k for k in list(self._backend.keys()) if isinstance(k, str) and k < today
                ]
                for k in yesterday_and_older:
                    try:
                        del self._backend[k]
                    except Exception:
                        pass
            except Exception:
                pass
            return True, count


def mark_interrupted_if_stale(job: dict | None, now: float | None = None) -> dict | None:
    """Return `job` flipped to a terminal error if it has been "running" too long.

    A job whose worker thread died on a container recycle stays frozen at its last
    stage with status "running". This surfaces that as status "error" (which the
    frontend already renders and the poller stops on) instead of a stuck spinner.
    Non-running or fresh jobs are returned unchanged.
    """
    if not job or job.get("status") != "running":
        return job
    if now is None:
        now = time.time()
    last = job.get("updated") or job.get("started") or 0
    if now - last > STALE_RUNNING_S:
        return {**job, "status": "error", "stage": "error", "error": INTERRUPTED_MSG}
    return job
