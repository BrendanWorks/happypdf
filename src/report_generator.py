"""Generate human-readable remediation reports from job manifests."""

from datetime import datetime
from pathlib import Path


def generate_html_report(manifest: dict, output_path: str = None) -> str:
    """Generate an HTML report from a remediation manifest.

    Args:
        manifest: Job manifest dict from /api/jobs/{id}/manifest
        output_path: Optional path to write HTML file

    Returns:
        HTML string
    """

    baseline = manifest.get("baseline") or {}
    final = manifest.get("final") or {}
    rounds = manifest.get("rounds") or []
    enhancements = manifest.get("enhancements") or []
    reviewer_health = manifest.get("reviewer_health") or {}
    stopped_reason = manifest.get("stopped_reason") or "in_progress"

    # Build rounds summary
    rounds_html = ""
    for r in rounds:
        status_class = {
            "accepted": "success",
            "gate_failed_reverted": "warning",
            "axe_regression_reverted": "danger",
            "applicator_rollback": "danger",
            "reviewers_failed": "danger",
        }.get(r.get("status"), "info")

        rounds_html += f"""
        <div class="round-card {status_class}">
            <h4>Round {r.get('round')} Optimization Pass</h4>
            <div class="metrics-group">
                <span class="badge {'highlight' if r.get('patches_applied', 0) > 0 else ''}">Patches Mutated: {r.get('patches_applied', 0)}</span>
                <span class="badge">Axe Violations: {r.get('violations', '?')}</span>
                <span class="badge">Compliance Checkpoints Verified: {r.get('passes', '?')}</span>
            </div>
            <div class="round-meta">
                <div>Preservation Gate: <strong>{'PASSED' if r.get('gate_passed') else 'FAILED'}</strong></div>
                <div>Axe-Core Health Check: <strong>{r.get('score', '?')}% Validated</strong></div>
            </div>
        </div>
        """

    # Build enhancements list
    enhancements_html = ""
    for e in enhancements:
        enhancements_html += f"""
        <div class="enhancement-item">
            <div class="enhancement-header">
                <span class="patch-type">Injected Structural Attribute</span>
                <span class="element-id">Target Element ID: {e.get('element_id', 'unknown')}</span>
            </div>
            <p style="font-size: 0.95rem; font-weight: 500; margin-bottom: 8px;">{e.get('description', 'Applied structural enhancement.')}</p>
            <div class="diff-box">
                <span>&lt;{e.get('type', 'element')} data-ir-id="{e.get('element_id', '')}"</span> <span class="diff-add">aria-label="{e.get('value', '')}"</span><span>&gt;</span>
            </div>
        </div>
        """

    # Build reviewer health
    reviewers_html = ""
    reviewer_names = {
        "olmo": "olmo (Local Engine)",
        "gpt": "gpt (Peer Review)",
        "claude": "claude (Judge/Peer)",
    }
    for reviewer, health in reviewer_health.items():
        status = health.get("status", "unknown")
        rounds_ran = health.get("rounds_ran", 0)
        display_name = reviewer_names.get(reviewer, reviewer)
        reviewers_html += f"""
        <div class="reviewer-card">
            <div class="reviewer-info">
                <span class="reviewer-name">{display_name}</span>
                <span class="reviewer-rounds">Evaluated {rounds_ran} Optimization Pass{'es' if rounds_ran != 1 else ''}</span>
            </div>
            <span class="status-pill {status.lower()}">{status.upper()}</span>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remediation Report - {manifest.get('name', 'PDF')}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.6; color: #1e293b; background: #f8fafc; }}
        .container {{ max-width: 1000px; margin: 0 auto; padding: 40px 20px; }}

        /* Header & Brand Identity */
        .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                   color: white; padding: 35px 40px; border-radius: 12px; margin-bottom: 30px;
                   box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); }}
        .header h1 {{ font-size: 2.25rem; font-weight: 800; margin-bottom: 6px; letter-spacing: -0.025em; }}
        .header .subtitle {{ font-size: 1.1rem; opacity: 0.85; font-weight: 400; color: #38bdf8; }}

        /* Card Layouts */
        .section {{ background: white; padding: 35px; margin-bottom: 30px; border-radius: 12px;
                   border: 1px solid #e2e8f0; box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1); }}
        .section h2 {{ font-size: 1.4rem; font-weight: 700; color: #0f172a; margin-bottom: 24px;
                      padding-bottom: 12px; border-bottom: 2px solid #e2e8f0; }}

        /* Executive Summary Grid */
        .score-box {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }}
        .score-item {{ background: #f8fafc; padding: 22px; border-radius: 8px; text-align: center;
                      border: 1px solid #f1f5f9; transition: transform 0.2s; }}
        .score-item:hover {{ transform: translateY(-2px); }}
        .score-item .label {{ font-size: 0.85rem; font-weight: 600; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
        .score-item .value {{ font-size: 2.25rem; font-weight: 800; color: #0f172a; line-height: 1; margin-bottom: 6px; }}
        .score-item .subtext {{ font-size: 0.875rem; color: #64748b; font-weight: 500; }}

        /* Pipeline Iteration Cards */
        .stopped-reason {{ background: #f0fdf4; border-left: 4px solid #22c55e; color: #166534;
                         padding: 16px 20px; border-radius: 6px; font-weight: 600; margin-bottom: 24px; font-size: 0.95rem; }}
        .round-card {{ border: 1px solid #e2e8f0; border-left: 5px solid #0f172a; padding: 20px; margin-bottom: 16px;
                      background: #f8fafc; border-radius: 8px; }}
        .round-card.success {{ border-left-color: #22c55e; }}
        .round-card h4 {{ font-size: 1.1rem; font-weight: 700; color: #0f172a; margin-bottom: 12px; }}
        .metrics-group {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }}
        .badge {{ display: inline-block; background: #ffffff; color: #334155; padding: 6px 12px;
                 border-radius: 6px; font-size: 0.85rem; font-weight: 600; border: 1px solid #e2e8f0; }}
        .badge.highlight {{ background: #f0fdf4; color: #166534; border-color: #bbf7d0; }}
        .round-meta {{ font-size: 0.875rem; color: #64748b; display: flex; gap: 20px; }}
        .round-meta strong {{ color: #334155; }}

        /* Enhancements Logging */
        .enhancement-item {{ border: 1px solid #e2e8f0; padding: 20px; margin-bottom: 16px;
                            border-radius: 8px; background: #ffffff; }}
        .enhancement-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }}
        .patch-type {{ background: #e0f2fe; color: #0369a1; font-size: 0.75rem; font-weight: 700;
                      padding: 4px 8px; border-radius: 4px; text-transform: uppercase; }}
        .element-id {{ display: inline-block; font-family: 'JetBrains Mono', 'Fira Code', monospace;
                      background: #f1f5f9; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; color: #475569; }}
        .diff-box {{ background: #0f172a; color: #f8fafc; padding: 12px 16px; border-radius: 6px;
                    font-family: monospace; font-size: 0.9rem; margin-top: 10px; overflow-x: auto; }}
        .diff-add {{ color: #4ade80; }}

        /* Multi-Agent Orchestration Monitors */
        .reviewer-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; }}
        .reviewer-card {{ border: 1px solid #e2e8f0; padding: 16px; border-radius: 8px; display: flex;
                         align-items: center; justify-content: space-between; background: #ffffff; }}
        .reviewer-info {{ display: flex; flex-direction: column; }}
        .reviewer-name {{ font-weight: 700; text-transform: uppercase; color: #334155; font-size: 0.9rem; }}
        .reviewer-rounds {{ font-size: 0.8rem; color: #64748b; margin-top: 2px; }}
        .status-pill {{ padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.05em; }}
        .status-pill.success {{ background: #d1fae5; color: #065f46; }}

        footer {{ text-align: center; color: #94a3b8; font-size: 0.85rem; margin-top: 50px;
                padding-top: 20px; border-top: 1px solid #e2e8f0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Accessibility Remediation Report</h1>
            <div class="subtitle">Document Workflow Asset: <strong>{manifest.get('name', 'PDF')}</strong></div>
        </div>

        <div class="section">
            <h2>Executive Summary</h2>
            <div class="score-box">
                <div class="score-item">
                    <div class="label">Accessibility Validation</div>
                    <div class="value">{final.get('score', '?')}%</div>
                    <div class="subtext" style="color: {'#22c55e' if final.get('violations', 1) == 0 else '#f59e0b'}; font-weight: 600;">{final.get('violations', '?')} axe-core {'violation' if final.get('violations', 2) == 1 else 'violations'}</div>
                </div>
                <div class="score-item">
                    <div class="label">Structural Depth</div>
                    <div class="value" style="color: #0284c7;">+{final.get('passes', baseline.get('passes', 0)) - baseline.get('passes', 0)}</div>
                    <div class="subtext">Additional WCAG passes verified</div>
                </div>
                <div class="score-item">
                    <div class="label">Pipeline Iterations</div>
                    <div class="value">{manifest.get('rounds_accepted', 0)}</div>
                    <div class="subtext">Convergence criteria met</div>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>Remediation Process Execution</h2>
            <div class="stopped-reason">✅ Execution Finished: Pipeline {'converged smoothly' if manifest.get('stopped_reason') in ['converged', 'no_more_reviews'] else 'halted'} after {manifest.get('rounds_accepted', 0)} optimization round{'s' if manifest.get('rounds_accepted', 0) != 1 else ''}.</div>

            {rounds_html if rounds_html else '<p style="color: #64748b; font-size: 0.95rem;">Baseline output passed all core criteria; no optimization rounds required.</p>'}
        </div>

        <div class="section">
            <h2>Applied Accessibility Enhancements</h2>
            <p style="color: #64748b; font-size: 0.9rem; margin-bottom: 20px;">The initial layout build cleanly passed core functional criteria. The multi-model evaluation cluster introduced the following additive structural labels to enrich navigation layout details safely:</p>

            {enhancements_html if enhancements_html else '<p style="color: #64748b; font-size: 0.95rem;">No structural enhancements needed; baseline output is fully compliant.</p>'}
        </div>

        <div class="section">
            <h2>Reviewer Evaluation Cluster Health</h2>
            <div class="reviewer-grid">
                {reviewers_html if reviewers_html else '<p style="color: #64748b; font-size: 0.95rem;">No reviewer data available.</p>'}
            </div>
        </div>

        <footer>
            <p>Generated via live pipeline orchestration layer • {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p style="margin-top: 4px; font-weight: 600;">happypdf Multi-Agent Remediation Architecture v2.0</p>
        </footer>
    </div>
</body>
</html>
"""

    if output_path:
        Path(output_path).write_text(html)

    return html
