#!/usr/bin/env bash
# Maintenance-window promotion: ships PointCheck Phases 2+3 to the prod API.
# (Phase 1 is already live; the alttext-judge Modal app is already deployed;
# the frontend already renders the new blocks and degrades gracefully.)
#
# Usage:      ./scripts/promote_prod.sh
# Rollback:   modal app rollback happypdf-api      (returns to the pre-window
#             version; the frontend hides the new sections automatically)
#
# Full runbook: docs/POINTCHECK_INTEGRATION.md + the July 16 memory handoff.
set -euo pipefail
cd "$(dirname "$0")/.."

PROD_URL="https://brendanworks--happypdf-api-fastapi-app.modal.run"

echo "== Pre-flight =="
git log --oneline -1
python3 -c "import ast; [ast.parse(open(f).read()) for f in
  ['api/main.py','src/build_syllabus_slice.py','src/fidelity_gate.py','src/pointcheck_scorer.py']]" \
  && echo "syntax OK"
python3 -m pytest tests/ -q | tail -1
python3 -c "
import modal
for fn in ('judge_alt_text', 'judge_page_fidelity'):
    modal.Function.from_name('alttext-judge', fn).hydrate()
    print(f'alttext-judge/{fn}: resolvable')"

echo "== Deploy prod API =="
modal deploy src/modal_api.py

echo "== Health =="
sleep 5
curl -sf -m 60 "$PROD_URL/api/health"
echo

cat <<'NEXT'
== Deploy done. Remaining manual steps ==
1. Prod e2e (verifies all three blocks populate; the critical fidelity
   finding for pages 1-2 is DETERMINISTIC — those pages have no text
   layer. Alt-text flags vary run to run with generation quality; all
   images being judged is the requirement, flags are not):
     python3 <scratchpad>/happypdf_e2e.py \
       https://brendanworks--happypdf-api-fastapi-app.modal.run \
       benchmark/navy_bulletin.pdf
2. UI + live data (the one path only prod can verify): upload a PDF at
   https://happypdf.org and confirm the three new results sections render.
3. If anything is wrong:  modal app rollback happypdf-api
NEXT
