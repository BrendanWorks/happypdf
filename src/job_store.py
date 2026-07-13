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
import time

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

    def __init__(self, on_modal: bool | None = None):
        if on_modal is None:
            on_modal = os.environ.get("HAPPYPDF_ON_MODAL") == "1"
        self._on_modal = on_modal
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

            self._dict = modal.Dict.from_name("happypdf-jobs", create_if_missing=True)
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
