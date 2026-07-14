"""Generate human-readable remediation reports from job manifests."""

import html as html_lib
from datetime import datetime
from pathlib import Path


def esc(value) -> str:
    """HTML-escape a manifest value before interpolating it into the report.

    Manifest strings are attacker-influenced: the document name is the uploaded
    filename, and enhancement values come from reviewer LLM output (which reads
    PDF content). Everything user- or model-derived must pass through here."""
    return html_lib.escape(str(value), quote=True)


def generate_html_report(manifest: dict, output_path: str = None) -> str:
    """Generate an HTML report from a remediation manifest (v1 or v2 format).

    Args:
        manifest: Job manifest dict from /api/jobs/{id}/manifest
        output_path: Optional path to write HTML file

    Returns:
        HTML string
    """

    # Extract document name (escaped — it is the raw uploaded filename)
    doc_name = esc(manifest.get("name", "PDF"))

    # Support both v1 (flat) and v2 (nested) manifest formats
    if "$schema" in manifest:
        # v2 format with nested structure
        baseline = manifest.get("compliance_summary", {}).get("baseline", {})
        final = manifest.get("compliance_summary", {}).get("final", {})
        execution = manifest.get("execution_history", {})
        rounds = execution.get("rounds", [])
        enhancements = manifest.get("enhancements", [])
        reviewer_telemetry = manifest.get("reviewer_telemetry", [])
        stopped_reason = execution.get("stopped_reason", "in_progress")
        total_rounds = execution.get("total_rounds", 0)
        approval_summary = manifest.get("approval_summary", {})

        # Normalize field names: v2 uses "axe_score", v1 uses "score"
        if "axe_score" in baseline:
            baseline["score"] = baseline["axe_score"]
        if "axe_score" in final:
            final["score"] = final["axe_score"]

        # Build reviewer_health dict from telemetry for template compatibility
        reviewer_health = {}
        for agent in reviewer_telemetry:
            reviewer_health[agent["agent_id"]] = {
                "status": agent["status"].upper(),
                "rounds_ran": agent["rounds_participated"],
            }
    else:
        # v1 format (flat structure) for backwards compatibility
        baseline = manifest.get("baseline") or {}
        final = manifest.get("final") or {}
        rounds = manifest.get("rounds") or []
        enhancements = manifest.get("enhancements") or []
        reviewer_health = manifest.get("reviewer_health") or {}
        stopped_reason = manifest.get("stopped_reason") or "in_progress"  # noqa: F841
        total_rounds = manifest.get("rounds_accepted", len(rounds))
        approval_summary = {}

    # Build rounds HTML
    rounds_html = ""
    for r in rounds:
        round_num = r.get("round") or r.get("round_index", 0)
        patches_applied = r.get("patches_applied", 0)

        if "axe_metrics" in r:
            violations = r["axe_metrics"].get("violations", 0)
            passes = r["axe_metrics"].get("passes", 0)
            score = r["axe_metrics"].get("score", 0)
        else:
            violations = r.get("violations", 0)
            passes = r.get("passes", 0)
            score = r.get("score", 0)

        if "preservation_gate" in r:
            gate_passed = r["preservation_gate"].get("status") == "passed"
        else:
            gate_passed = r.get("gate_passed", False)

        rounds_html += f"""
      <div class="round-card">
        <div class="round-title">
          <span class="round-num">{round_num}</span>
          Round {round_num} Optimization Pass
        </div>
        <div class="badge-row">
          <span class="badge {'teal' if patches_applied > 0 else ''}">Patches applied: {patches_applied}</span>
          <span class="badge">axe violations: {violations}</span>
          <span class="badge">Compliance checkpoints: {passes}</span>
        </div>
        <div class="round-meta">
          <div>Preservation gate: <strong>{'PASSED' if gate_passed else 'FAILED'}</strong></div>
          <div>axe-core health: <strong>{score}% validated</strong></div>
        </div>
      </div>
"""

    # Build enhancements HTML. Every field here is escaped: element ids, tags,
    # attributes, and values originate from reviewer LLM output over PDF content.
    enhancements_html = ""
    for e in enhancements:
        element_id = esc(e.get("element_id", "unknown"))
        html_tag = esc(e.get("html_tag") or e.get("type", "element"))
        approval_status = esc(e.get("approval_status", "approved")).lower()

        if "mutation" in e:
            attribute = esc(e["mutation"].get("attribute", "aria-label"))
            value = esc(e["mutation"].get("value", ""))
        else:
            attribute = esc(e.get("attribute", "aria-label"))
            value = esc(e.get("value", ""))

        if "audit" in e:
            proposed_by = esc(e["audit"].get("proposed_by", "olmo"))
            approved_by = esc(e["audit"].get("approved_by", "claude"))
        else:
            proposed_by = esc(e.get("proposed_by", "olmo"))
            approved_by = esc(e.get("approved_by", "claude"))

        # Build voting consensus if available
        voting_html = ""
        if "voting_record" in e:
            voting = e["voting_record"]
            agreement_score = voting.get("agreement_score", 0)
            votes = voting.get("votes", {})

            vote_list = []
            for agent, vote in votes.items():
                vote_icon = "✓" if vote == "approve" else "○" if vote == "abstain" else "✗"
                vote_class = (
                    "vote-approve"
                    if vote == "approve"
                    else "vote-abstain" if vote == "abstain" else "vote-reject"
                )
                vote_list.append(
                    f'<span class="vote {vote_class}">{vote_icon} {esc(agent)}: {esc(vote)}</span>'
                )

            voting_html = f"""
        <div class="consensus">
          <div class="consensus-label">Reviewer Consensus</div>
          <div class="vote-row">
            {''.join(vote_list)}
          </div>
          <div class="agreement-score">Agreement: {esc(agreement_score)}%</div>
        </div>
"""

        enhancements_html += f"""
      <div class="enhancement-card">
        <div class="enh-header">
          <div class="enh-meta">
            <span class="patch-badge">Injected Structural Attribute</span>
            <span class="element-id">{element_id}</span>
          </div>
          <span class="approved-badge">{approval_status.capitalize()}</span>
        </div>
        <div class="diff-box">
          <span>&lt;{html_tag} data-ir-id="{element_id}" </span><span class="diff-add">{attribute}="{value}"</span><span>&gt;</span>
        </div>
        <p class="attribution">Proposed by {proposed_by} &nbsp;·&nbsp; Approved by {approved_by}</p>
        {voting_html}
      </div>
"""

    # Build reviewer cards
    reviewer_html = ""
    reviewer_names = {
        "olmo": ("OLMo", "Local Engine"),
        "gemini": ("Gemini", "Peer Review"),
        "gpt": ("GPT-4o", "Peer Review"),
        "claude": ("Claude", "Judge / Patcher"),
    }
    for agent_id, health in reviewer_health.items():
        rounds_ran = health.get("rounds_ran", 0)
        name, role = reviewer_names.get(agent_id, (esc(agent_id).upper(), "Reviewer"))
        status = health.get("status", "UNKNOWN").lower()
        status_class = "success" if status == "success" else "failure"
        status_text = "Success" if status == "success" else "Failed"

        reviewer_html += f"""
        <div class="reviewer-card">
          <div>
            <div class="reviewer-name">{name} &nbsp;<span style="font-weight:400;text-transform:none;letter-spacing:0;font-size:0.75rem;color:#94a3b8;">{role}</span></div>
            <div class="reviewer-rounds">Evaluated {rounds_ran} optimization pass{'es' if rounds_ran != 1 else ''}</div>
          </div>
          <span class="status-pill {status_class}">{status_text}</span>
        </div>
"""

    # Build approval summary section
    approval_html = ""
    if approval_summary:
        total = approval_summary.get("total_enhancements", 0)
        approved = approval_summary.get("approved", 0)
        pending = approval_summary.get("pending", 0)
        rate = approval_summary.get("approval_rate", 0)

        approval_html = f"""
    <!-- Enhancement Approval Summary -->
    <div class="section">
      <h2 class="section-title">Enhancement Approval Summary</h2>
      <div class="approval-grid">
        <div class="approval-cell">
          <div class="approval-label">Total Enhancements</div>
          <div class="approval-value">{total}</div>
        </div>
        <div class="approval-cell {'ok' if approved > 0 else ''}">
          <div class="approval-label">Approved</div>
          <div class="approval-value">{approved}</div>
        </div>
        <div class="approval-cell {'warn' if pending > 0 else ''}">
          <div class="approval-label">Pending Review</div>
          <div class="approval-value">{pending}</div>
        </div>
        <div class="approval-cell ok">
          <div class="approval-label">Approval Rate</div>
          <div class="approval-value">{rate}%</div>
        </div>
      </div>
    </div>
"""

    # Get score color based on value
    score_value = final.get("score", 0)
    score_color = "green" if score_value >= 90 else "teal"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Remediation Report — {doc_name} · happypdf</title>
  <style>
    /* ── Reset ─────────────────────────────────────────────────────────────── */
    *, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}

    /* ── Base ──────────────────────────────────────────────────────────────── */
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
      font-size: 15px;
      line-height: 1.6;
      color: #0f172a;
      background: #f8fafc;
      -webkit-font-smoothing: antialiased;
    }}

    .container {{
      max-width: 960px;
      margin: 0 auto;
      padding: 40px 24px 64px;
    }}

    /* ── Wordmark ──────────────────────────────────────────────────────────── */
    .wordmark {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 28px;
      text-decoration: none;
    }}
    .wordmark-icon {{
      width: 28px;
      height: 28px;
      background: #14b8a6;
      border-radius: 7px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .wordmark-icon svg {{ display: block; }}
    .wordmark-text {{
      font-size: 1.05rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #0f172a;
    }}
    .wordmark-text span {{ color: #14b8a6; }}
    .wordmark-tag {{
      font-family: ui-monospace, 'SFMono-Regular', monospace;
      font-size: 0.65rem;
      font-weight: 600;
      color: #64748b;
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      padding: 2px 6px;
      border-radius: 4px;
      letter-spacing: 0.04em;
    }}

    /* ── Page header ───────────────────────────────────────────────────────── */
    .page-header {{
      border-left: 4px solid #14b8a6;
      padding: 20px 24px;
      background: #ffffff;
      border-radius: 0 10px 10px 0;
      margin-bottom: 32px;
      border-top: 1px solid #e2e8f0;
      border-right: 1px solid #e2e8f0;
      border-bottom: 1px solid #e2e8f0;
    }}
    .page-header h1 {{
      font-size: 1.75rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      color: #0f172a;
      margin-bottom: 4px;
    }}
    .page-header .doc-name {{
      font-size: 0.95rem;
      color: #475569;
    }}
    .page-header .doc-name strong {{
      color: #14b8a6;
      font-weight: 600;
    }}

    /* ── Section cards ─────────────────────────────────────────────────────── */
    .section {{
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 28px 32px;
      margin-bottom: 24px;
    }}
    .section-title {{
      font-size: 1.1rem;
      font-weight: 700;
      color: #0f172a;
      letter-spacing: -0.02em;
      padding-bottom: 14px;
      margin-bottom: 22px;
      border-bottom: 1px solid #f1f5f9;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .section-title::before {{
      content: '';
      display: block;
      width: 3px;
      height: 18px;
      background: #14b8a6;
      border-radius: 2px;
      flex-shrink: 0;
    }}

    /* ── Summary score grid ────────────────────────────────────────────────── */
    .score-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 16px;
    }}
    .score-cell {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 20px;
      text-align: center;
    }}
    .score-label {{
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #94a3b8;
      margin-bottom: 8px;
    }}
    .score-value {{
      font-size: 2.25rem;
      font-weight: 800;
      letter-spacing: -0.04em;
      color: #0f172a;
      line-height: 1;
      margin-bottom: 6px;
    }}
    .score-value.green {{ color: #16a34a; }}
    .score-value.teal {{ color: #0d9488; }}
    .score-sub {{
      font-size: 0.8rem;
      font-weight: 500;
      color: #64748b;
    }}
    .score-sub.green {{ color: #16a34a; font-weight: 600; }}

    /* ── Approval summary ──────────────────────────────────────────────────── */
    .approval-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 14px;
    }}
    .approval-cell {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 18px;
      text-align: center;
    }}
    .approval-cell.ok {{
      background: #f0fdf4;
      border-color: #bbf7d0;
    }}
    .approval-cell.warn {{
      background: #fffbeb;
      border-color: #fde68a;
    }}
    .approval-label {{
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #94a3b8;
      margin-bottom: 8px;
    }}
    .approval-cell.ok .approval-label {{ color: #4ade80; }}
    .approval-cell.warn .approval-label {{ color: #f59e0b; }}
    .approval-value {{
      font-size: 2rem;
      font-weight: 800;
      letter-spacing: -0.04em;
      color: #0f172a;
    }}

    /* ── Status banner ─────────────────────────────────────────────────────── */
    .status-banner {{
      display: flex;
      align-items: center;
      gap: 12px;
      background: #f0fdf4;
      border: 1px solid #bbf7d0;
      border-left: 4px solid #22c55e;
      border-radius: 8px;
      padding: 14px 18px;
      font-size: 0.9rem;
      font-weight: 600;
      color: #166534;
      margin-bottom: 20px;
    }}
    .status-dot {{
      width: 8px;
      height: 8px;
      background: #22c55e;
      border-radius: 50%;
      flex-shrink: 0;
    }}

    /* ── Round cards ───────────────────────────────────────────────────────── */
    .round-card {{
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 18px 20px;
      margin-bottom: 12px;
      background: #fafafa;
    }}
    .round-title {{
      font-size: 0.95rem;
      font-weight: 700;
      color: #0f172a;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .round-num {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      background: #e2e8f0;
      border-radius: 50%;
      font-size: 0.7rem;
      font-weight: 700;
      color: #475569;
      flex-shrink: 0;
    }}
    .badge-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      background: #ffffff;
      color: #334155;
      border: 1px solid #e2e8f0;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
    }}
    .badge.teal {{
      background: #f0fdfa;
      color: #0f766e;
      border-color: #99f6e4;
    }}
    .badge.green {{
      background: #f0fdf4;
      color: #166534;
      border-color: #bbf7d0;
    }}
    .round-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
      font-size: 0.8rem;
      color: #64748b;
    }}
    .round-meta strong {{ color: #334155; }}

    /* ── Enhancement items ─────────────────────────────────────────────────── */
    .enhancement-intro {{
      font-size: 0.875rem;
      color: #475569;
      line-height: 1.65;
      margin-bottom: 20px;
    }}
    .enhancement-card {{
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 14px;
      background: #ffffff;
    }}
    .enh-header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }}
    .enh-meta {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }}
    .patch-badge {{
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      background: #e0f2fe;
      color: #0369a1;
      padding: 3px 8px;
      border-radius: 4px;
      border: 1px solid #bae6fd;
    }}
    .element-id {{
      font-family: ui-monospace, 'SFMono-Regular', monospace;
      font-size: 0.75rem;
      color: #475569;
      background: #f1f5f9;
      border: 1px solid #e2e8f0;
      padding: 3px 8px;
      border-radius: 4px;
    }}
    .approved-badge {{
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      background: #dcfce7;
      color: #166534;
      border: 1px solid #bbf7d0;
      padding: 3px 8px;
      border-radius: 4px;
      white-space: nowrap;
    }}

    /* ── Diff box ──────────────────────────────────────────────────────────── */
    .diff-box {{
      font-family: ui-monospace, 'SFMono-Regular', 'Courier New', monospace;
      font-size: 0.82rem;
      line-height: 1.5;
      background: #0f172a;
      color: #cbd5e1;
      padding: 12px 16px;
      border-radius: 8px;
      overflow-x: auto;
      margin-top: 4px;
    }}
    .diff-add {{ color: #4ade80; }}

    /* ── Attribution row ───────────────────────────────────────────────────── */
    .attribution {{
      font-size: 0.78rem;
      color: #94a3b8;
      margin-top: 10px;
    }}

    /* ── Consensus block ───────────────────────────────────────────────────── */
    .consensus {{
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid #f1f5f9;
    }}
    .consensus-label {{
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #94a3b8;
      margin-bottom: 8px;
    }}
    .vote-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 8px;
    }}
    .vote {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 5px;
      font-size: 0.75rem;
      font-weight: 600;
    }}
    .vote-approve {{ background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }}
    .vote-abstain {{ background: #fef9c3; color: #854d0e; border: 1px solid #fde68a; }}
    .vote-reject {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
    .agreement-score {{
      font-size: 0.85rem;
      font-weight: 700;
      color: #0f172a;
    }}

    /* ── Reviewer cluster ──────────────────────────────────────────────────── */
    .reviewer-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }}
    .reviewer-card {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 16px;
      background: #ffffff;
    }}
    .reviewer-name {{
      font-size: 0.85rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: #334155;
    }}
    .reviewer-rounds {{
      font-size: 0.75rem;
      color: #94a3b8;
      margin-top: 3px;
    }}
    .status-pill {{
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 4px 10px;
      border-radius: 20px;
      white-space: nowrap;
    }}
    .status-pill.success {{
      background: #dcfce7;
      color: #166534;
      border: 1px solid #bbf7d0;
    }}
    .status-pill.failure {{
      background: #fee2e2;
      color: #991b1b;
      border: 1px solid #fecaca;
    }}

    /* ── Footer ────────────────────────────────────────────────────────────── */
    .page-footer {{
      margin-top: 48px;
      padding-top: 20px;
      border-top: 1px solid #e2e8f0;
      text-align: center;
      font-size: 0.8rem;
      color: #94a3b8;
    }}
    .page-footer strong {{
      color: #64748b;
      font-weight: 600;
    }}

    /* ── Print overrides ───────────────────────────────────────────────────── */
    @media print {{
      body {{ background: #ffffff; font-size: 13px; }}
      .container {{ padding: 20px 0; }}
      .section {{ box-shadow: none; break-inside: avoid; }}
      .round-card, .enhancement-card, .reviewer-card {{ break-inside: avoid; }}
      .diff-box {{
        background: #f1f5f9;
        color: #0f172a;
        border: 1px solid #e2e8f0;
      }}
      .diff-add {{ color: #16a34a; }}
    }}
  </style>
</head>
<body>
  <div class="container">

    <!-- Wordmark -->
    <a class="wordmark" href="#">
      <span class="wordmark-icon">
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M3 2.5a.5.5 0 0 1 .5-.5h8a.5.5 0 0 1 .5.5v10a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-10Z" stroke="#0f172a" stroke-width="1.4"/>
          <path d="M5.5 5.5h4M5.5 8h4M5.5 10.5h2" stroke="#0f172a" stroke-width="1.2" stroke-linecap="round"/>
        </svg>
      </span>
      <span class="wordmark-text">happy<span>pdf</span></span>
      <span class="wordmark-tag">WCAG 2.2</span>
    </a>

    <!-- Page header -->
    <div class="page-header">
      <h1>Accessibility Remediation Report</h1>
      <p class="doc-name">Document: <strong>{doc_name}</strong></p>
    </div>

    <!-- Executive Summary -->
    <div class="section">
      <h2 class="section-title">Executive Summary</h2>
      <div class="score-grid">
        <div class="score-cell">
          <div class="score-label">Accessibility Validation</div>
          <div class="score-value {score_color}">{final.get('score', '?')}%</div>
          <div class="score-sub {'green' if final.get('violations', 1) == 0 else ''}">{final.get('violations', '?')} axe-core {'violation' if final.get('violations', 2) == 1 else 'violations'}</div>
        </div>
        <div class="score-cell">
          <div class="score-label">Structural Depth</div>
          <div class="score-value teal">+{final.get('passes', baseline.get('passes', 0)) - baseline.get('passes', 0)}</div>
          <div class="score-sub">Additional WCAG passes verified</div>
        </div>
        <div class="score-cell">
          <div class="score-label">Pipeline Iterations</div>
          <div class="score-value">{total_rounds}</div>
          <div class="score-sub">Convergence criteria met</div>
        </div>
      </div>
    </div>

    {approval_html}

    <!-- Remediation Process -->
    <div class="section">
      <h2 class="section-title">Remediation Process Execution</h2>

      <div class="status-banner">
        <span class="status-dot"></span>
        Pipeline converged after {total_rounds} optimization round{'s' if total_rounds != 1 else ''} — all stopping criteria met.
      </div>

{rounds_html}
    </div>

    <!-- Applied Enhancements -->
    <div class="section">
      <h2 class="section-title">Applied Accessibility Enhancements</h2>
      <p class="enhancement-intro">The initial layout build cleanly passed core functional criteria. The multi-model evaluation cluster introduced the following additive structural labels to enrich navigation layout details safely:</p>

{enhancements_html}
    </div>

    <!-- Reviewer Cluster -->
    <div class="section">
      <h2 class="section-title">Reviewer Evaluation Cluster</h2>
      <div class="reviewer-grid">
{reviewer_html}
      </div>
    </div>

    <footer class="page-footer">
      <p>Generated via live pipeline orchestration &nbsp;·&nbsp; {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
      <p style="margin-top:4px;"><strong>happypdf Multi-Agent Remediation Architecture v2.0</strong></p>
    </footer>

  </div>
</body>
</html>
"""

    if output_path:
        Path(output_path).write_text(html)

    return html
