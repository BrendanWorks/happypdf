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
            <h4>Round {r.get('round')}</h4>
            <div class="metrics">
                <span class="badge">Patches: {r.get('patches_applied', 0)}</span>
                <span class="badge">Rejected: {r.get('rejected', 0)}</span>
                <span class="badge">Score: {r.get('score', '?')}%</span>
                <span class="badge">Violations: {r.get('violations', '?')}</span>
                <span class="badge">Passes: {r.get('passes', '?')}</span>
            </div>
            <p class="status">Status: <strong>{r.get('status', 'unknown')}</strong> ({r.get('seconds', 0)}s)</p>
            <p class="gate">Gate: <strong>{'PASSED' if r.get('gate_passed') else 'FAILED'}</strong></p>
            {"".join(f'<p class="check">✓ {c.get("name", "Check")}</p>' for c in (r.get("gate_checks") or []) if c and c.get("passed"))}
            {"".join(f'<p class="check-fail">✗ {c.get("name", "Check")}: {c.get("detail", "")}</p>' for c in (r.get("gate_checks") or []) if c and not c.get("passed"))}
        </div>
        """

    # Build enhancements list
    enhancements_html = ""
    for e in enhancements:
        enhancements_html += f"""
        <div class="enhancement-item">
            <p><strong>{e.get('type', 'Unknown')}</strong>: {e.get('description', '')}</p>
            <code class="element-id">{e.get('element_id', '')}</code>
        </div>
        """

    # Build reviewer health
    reviewers_html = ""
    for reviewer, health in reviewer_health.items():
        status = health.get("status", "unknown")
        rounds_ran = health.get("rounds_ran", 0)
        reviewers_html += f"""
        <div class="reviewer">
            <span class="name">{reviewer}</span>
            <span class="status {status}">{status.upper()}</span>
            <span class="info">({rounds_ran} rounds)</span>
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
                line-height: 1.6; color: #333; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 40px 20px; }}
        .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                   color: white; padding: 40px; border-radius: 8px; margin-bottom: 40px; }}
        .header h1 {{ font-size: 2em; margin-bottom: 10px; }}
        .header .subtitle {{ font-size: 1em; opacity: 0.9; }}
        .section {{ background: white; padding: 30px; margin-bottom: 30px; border-radius: 8px;
                   box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .section h2 {{ font-size: 1.5em; margin-bottom: 20px; border-bottom: 2px solid #14b8a6;
                      padding-bottom: 10px; }}
        .score-box {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                     gap: 20px; margin-bottom: 20px; }}
        .score-item {{ background: #f9fafb; padding: 20px; border-radius: 6px; text-align: center; }}
        .score-item .label {{ font-size: 0.9em; color: #666; margin-bottom: 8px; }}
        .score-item .value {{ font-size: 2em; font-weight: bold; color: #14b8a6; }}
        .badge {{ display: inline-block; background: #e0f2f1; color: #00796b; padding: 4px 12px;
                 border-radius: 12px; margin-right: 10px; margin-bottom: 8px; font-size: 0.9em; }}
        .round-card {{ border-left: 4px solid #0f172a; padding: 20px; margin-bottom: 15px;
                      background: #fafafa; border-radius: 4px; }}
        .round-card h4 {{ margin-bottom: 15px; color: #0f172a; }}
        .round-card.success {{ border-left-color: #22c55e; }}
        .round-card.warning {{ border-left-color: #f59e0b; }}
        .round-card.danger {{ border-left-color: #ef4444; }}
        .metrics {{ margin-bottom: 15px; }}
        .status, .gate {{ margin: 8px 0; }}
        .check {{ color: #22c55e; margin: 6px 0; }}
        .check-fail {{ color: #ef4444; margin: 6px 0; }}
        .enhancement-item {{ border: 1px solid #e5e7eb; padding: 15px; margin-bottom: 12px;
                            border-radius: 4px; }}
        .element-id {{ display: block; background: #f3f4f6; padding: 8px 12px;
                      border-radius: 4px; font-size: 0.9em; margin-top: 8px; }}
        .reviewer {{ display: inline-flex; align-items: center; gap: 10px;
                   background: #f3f4f6; padding: 10px 15px; border-radius: 6px; margin: 8px 8px 8px 0; }}
        .reviewer .name {{ font-weight: 600; }}
        .reviewer .status {{ padding: 2px 8px; border-radius: 4px; font-size: 0.85em; font-weight: 600; }}
        .reviewer .status.success {{ background: #d1fae5; color: #065f46; }}
        .reviewer .status.failed {{ background: #fee2e2; color: #7f1d1d; }}
        .reviewer .info {{ font-size: 0.9em; color: #666; }}
        .stopped-reason {{ background: #f0fdf4; border-left: 4px solid #22c55e; padding: 15px;
                         border-radius: 4px; margin-bottom: 20px; }}
        .stopped-reason.failed {{ background: #fef2f2; border-left-color: #ef4444; }}
        footer {{ text-align: center; color: #666; font-size: 0.9em; margin-top: 40px;
                padding-top: 20px; border-top: 1px solid #e5e7eb; }}
        code {{ font-family: 'Monaco', 'Menlo', monospace; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>PDF Remediation Report</h1>
            <p class="subtitle">{manifest.get('name', 'Untitled Document')}</p>
        </div>

        <div class="section">
            <h2>Executive Summary</h2>
            <div class="score-box">
                <div class="score-item">
                    <div class="label">Baseline Score</div>
                    <div class="value">{baseline.get('score', '?')}%</div>
                    <div style="font-size: 0.9em; color: #666;">{baseline.get('violations', '?')} violations</div>
                </div>
                <div class="score-item">
                    <div class="label">Final Score</div>
                    <div class="value">{final.get('score', '?')}%</div>
                    <div style="font-size: 0.9em; color: #666;">{final.get('violations', '?')} violations</div>
                </div>
                <div class="score-item">
                    <div class="label">Improvement</div>
                    <div class="value" style="color: {'#22c55e' if final.get('score', 0) >= baseline.get('score', 0) else '#ef4444'};">
                        {'+' if final.get('score', 0) >= baseline.get('score', 0) else ''}{final.get('score', 0) - baseline.get('score', 0):.1f}%
                    </div>
                </div>
                <div class="score-item">
                    <div class="label">Rounds</div>
                    <div class="value">{manifest.get('rounds_accepted', 0)}</div>
                    <div style="font-size: 0.9em; color: #666;">Stopped: {stopped_reason.replace('_', ' ')}</div>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>Remediation Process</h2>
            {f'<div class="stopped-reason failed">Stopped: {stopped_reason.replace("_", " ")}</div>' if stopped_reason not in ['converged', 'no_more_reviews'] else f'<div class="stopped-reason">Converged after {manifest.get("rounds_accepted", 0)} round(s)</div>'}
            {rounds_html if rounds_html else '<p>No rounds executed.</p>'}
        </div>

        <div class="section">
            <h2>Accessibility Enhancements</h2>
            {enhancements_html if enhancements_html else '<p>No enhancements needed.</p>'}
        </div>

        <div class="section">
            <h2>Reviewer Health</h2>
            {reviewers_html if reviewers_html else '<p>No reviewer data available.</p>'}
        </div>

        <footer>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p>happypdf Remediation Report v1.0</p>
        </footer>
    </div>
</body>
</html>
"""

    if output_path:
        Path(output_path).write_text(html)

    return html
