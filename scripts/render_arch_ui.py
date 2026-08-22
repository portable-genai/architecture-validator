"""Render the audit-first intake-gate UI from the demo JSON into static HTML pages.

Server-side, dependency-free rendering of a :class:`ValidationReport` (one page per
case plus an index), faithful to the existing Next.js console palette (ink / regblue,
Panel, status pills, citation chips) in ``ui/``. Used to produce screenshots for slides
from the synthetic testing data.

    PYTHONPATH=src:tests python scripts/render_arch_ui.py arch_demo.json out_dir/
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

# Status -> (bg, fg) — mirrors STATUS_TONE in ui/lib/types.ts.
STATUS_COLOR = {
    "PASS": ("#ecfdf5", "#047857"),
    "FAIL": ("#fff1f2", "#be123c"),
    "NEEDS_INFO": ("#fffbeb", "#b45309"),
    "NOT_APPLICABLE": ("#f5f7fa", "#546b8b"),
}
SEV_COLOR = {
    "low": ("#eef2f7", "#546b8b"),
    "medium": ("#fef3c7", "#92400e"),
    "high": ("#ffedd5", "#c2410c"),
    "critical": ("#fee2e2", "#b91c1c"),
}

CSS = """
:root{--ink-50:#f5f7fa;--ink-100:#e6ebf2;--ink-200:#cdd7e4;--ink-300:#a6b6cc;
--ink-400:#7790ae;--ink-500:#546b8b;--ink-600:#3f5470;--ink-700:#33445b;--ink-800:#1f2a3a;
--ink-900:#111827;
--regblue-50:#eef4ff;--regblue-100:#dbe7ff;--regblue-600:#2945d6;--regblue-700:#2237ad;
--ok:#059669;--ok-bg:#ecfdf5;--warn:#d97706;--warn-bg:#fffbeb;--fail:#be123c;--fail-bg:#fff1f2;
--shadow:0 1px 2px rgba(11,16,26,.06),0 8px 24px rgba(11,16,26,.06);}
*{box-sizing:border-box}
body{margin:0;background:var(--ink-50);color:var(--ink-800);
font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
font-size:14px;line-height:1.5;padding:24px 18px}
.wrap{max-width:920px;margin:0 auto}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
h1{font-size:18px;margin:0 0 2px}
.sub{color:var(--ink-500);font-size:13px;margin:0 0 16px}
.sub b{color:var(--ink-800)}
.topbar{display:flex;align-items:center;gap:10px;margin:0 0 16px}
.logo{width:30px;height:30px;border-radius:8px;background:var(--regblue-600);color:#fff;
font-weight:800;font-size:13px;display:flex;align-items:center;justify-content:center}
.verdict{border-radius:12px;padding:12px 16px;margin-bottom:16px;border:1px solid}
.verdict.pass{background:var(--ok-bg);border-color:#a7f3d0;color:#047857}
.verdict.fail{background:var(--fail-bg);border-color:#fecdd3;color:var(--fail)}
.verdict .head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.verdict .v{font-size:15px;font-weight:700}
.verdict .meta{font-size:11px;opacity:.85;margin-top:2px}
.verdict .counts{font-size:11px;text-align:right;white-space:nowrap}
.verdict .review{margin:8px 0 0;font-size:12px;font-weight:600}
.panel{border:1px solid var(--ink-200);background:#fff;border-radius:10px;box-shadow:var(--shadow);margin-bottom:16px}
.panel>h2{border-bottom:1px solid var(--ink-100);padding:11px 16px;margin:0;font-size:13px;font-weight:600;color:var(--ink-800);
display:flex;justify-content:space-between;align-items:center}
.panel>h2 .muted{font-weight:400}
.panel>.body{padding:8px 16px}
.finding{padding:11px 0;border-bottom:1px solid var(--ink-100)}
.finding:last-child{border-bottom:0}
.finding .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pid{font-family:ui-monospace,Menlo,monospace;font-weight:700;color:var(--ink-800)}
.pill{font-size:11px;font-weight:700;padding:2px 9px;border-radius:999px}
.sev{font-size:11px;font-weight:600;text-transform:lowercase}
.rule{margin-left:auto;font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--ink-400)}
.finding .ev{margin:4px 0 0;font-size:13px;color:var(--ink-700)}
.finding .rem{margin:3px 0 0;font-size:12px;color:var(--ink-500)}
.finding .rem b{color:var(--ink-600)}
.chips{margin-top:5px;display:flex;gap:5px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--ink-200);background:var(--ink-50);border-radius:6px;padding:1px 7px;font-size:11px;color:var(--ink-700)}
.chip .ty{font-family:ui-monospace,Menlo,monospace;font-weight:600;color:var(--regblue-700)}
.chip .sr{font-family:ui-monospace,Menlo,monospace}
.inj{padding:10px 0;border-bottom:1px solid var(--ink-100)}
.inj:last-child{border-bottom:0}
.inj .req{font-size:13px;color:var(--ink-800)}
.inj .req .pid{margin-right:6px;color:var(--regblue-700)}
.inj .rat{font-size:12px;color:var(--ink-500);margin-top:2px}
.empty{color:var(--ok);font-size:13px;background:var(--ok-bg);border:1px solid #a7f3d0;border-radius:8px;padding:10px 12px;margin:6px 0}
.kv{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;color:var(--ink-500)}
.kv b{color:var(--ink-800)}
.foot{font-size:11px;color:var(--ink-400);text-align:center;margin-top:18px}
.idx{display:grid;gap:12px}
.idx a{text-decoration:none;color:inherit}
.idxcard{border:1px solid var(--ink-200);background:#fff;border-radius:10px;box-shadow:var(--shadow);padding:14px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px}
.idxcard .v{font-weight:700}
.idxcard.pass .v{color:#047857}.idxcard.fail .v{color:var(--fail)}
"""


def esc(s: object) -> str:
    return html.escape(str(s if s is not None else ""))


def status_pill(status: str) -> str:
    bg, fg = STATUS_COLOR.get(status, STATUS_COLOR["NOT_APPLICABLE"])
    return f'<span class="pill" style="background:{bg};color:{fg}">{esc(status)}</span>'


def sev_color(sev: str) -> str:
    _, fg = SEV_COLOR.get(sev, SEV_COLOR["low"])
    return fg


def chip(c: dict) -> str:
    reg = c.get("regulator", "")
    page = f" p.{c['page']}" if c.get("page") is not None else ""
    return (
        f'<span class="chip"><span class="ty">{esc(reg)}</span>'
        f'<span class="sr">{esc(c.get("source_id"))}{esc(page)}</span></span>'
    )


def render_verdict(report: dict) -> str:
    sub = report["submission"]
    passed = report["passed"]
    findings = report["findings"]
    fails = [f for f in findings if f["status"] == "FAIL"]
    cls = "pass" if passed else "fail"
    title = "PASS — clears intake" if passed else "FAIL — blocked at intake"
    review = (
        '<p class="review">HUMAN REVIEW REQUIRED — maker-checker gate (P-06). '
        "A qualified reviewer must sign off before intake proceeds.</p>"
        if report["requires_human_review"]
        else ""
    )
    return (
        f'<div class="verdict {cls}" data-verdict="{"PASS" if passed else "FAIL"}" '
        f'data-submission="{esc(sub["id"])}" '
        f'data-principles-checked="{len(findings)}" '
        f'data-fail-count="{len(fails)}" '
        f'data-injected-count="{len(report["injected_requirements"])}" '
        f'data-review-required="{str(bool(report["requires_human_review"])).lower()}">'
        f'<div class="head">'
        f'<div><div class="v">{esc(title)}</div>'
        f'<div class="meta">{esc(sub["id"])} · {esc(sub["name"])}</div></div>'
        f'<div class="counts">{len(findings)} principles checked<br>'
        f"{len(fails)} failing · {len(report['injected_requirements'])} requirements injected</div>"
        f"</div>{review}</div>"
    )


def render_submission(sub: dict) -> str:
    controls = ", ".join(sub.get("declared_controls", [])) or "none"
    flags = (
        ", ".join(
            n
            for n, v in (
                ("PII", sub.get("uses_pii")),
                ("RAG", sub.get("uses_rag")),
                ("fine-tuning", sub.get("uses_fine_tuning")),
                ("exit plan", sub.get("has_exit_plan")),
            )
            if v
        )
        or "none"
    )
    return (
        '<section class="panel" data-panel="project-submission" '
        f'data-submission-region="{esc(sub.get("declared_region"))}" '
        f'data-submission-controls="{len(sub.get("declared_controls", []))}">'
        "<h2>Project submission "
        '<span class="muted">POST /validate · intake gate (R6)</span></h2>'
        '<div class="body"><div class="kv" style="padding:8px 0">'
        f"<span>region <b class='mono'>{esc(sub.get('declared_region'))}</b></span>"
        f"<span>flags <b>{esc(flags)}</b></span>"
        f"<span>declared controls <b>{esc(controls)}</b></span></div>"
        f"<p class='rem' style='color:var(--ink-500)'>{esc(sub.get('description'))}</p>"
        "</div></section>"
    )


def render_findings(findings: list[dict]) -> str:
    rows = []
    for f in findings:
        cites = "".join(chip(c) for c in f.get("citations", []))
        rem = (
            f'<p class="rem"><b>remediation:</b> {esc(f["remediation"])}</p>'
            if f.get("remediation")
            else ""
        )
        rows.append(
            f'<div class="finding" data-finding="{esc(f["principle_id"])}" '
            f'data-finding-status="{esc(f["status"])}" '
            f'data-finding-severity="{esc(f["severity"])}" '
            f'data-finding-citations="{len(f.get("citations", []))}">'
            '<div class="row">'
            f'<span class="pid">{esc(f["principle_id"])}</span>'
            f"{status_pill(f['status'])}"
            f'<span class="sev" style="color:{sev_color(f["severity"])}">{esc(f["severity"])}</span>'
            f'<span class="rule">{esc(f["rule_id"])}</span></div>'
            f'<p class="ev">{esc(f["evidence"])}</p>{rem}'
            f'<div class="chips">{cites}</div></div>'
        )
    fails = sum(1 for f in findings if f["status"] == "FAIL")
    return (
        '<section class="panel" data-panel="principle-findings" '
        f'data-findings-count="{len(findings)}" data-findings-failing="{fails}">'
        "<h2>Principle findings "
        '<span class="muted">one per principle · PASS only if no FAIL</span></h2>'
        f'<div class="body">{"".join(rows)}</div></section>'
    )


def render_injected(injected: list[dict]) -> str:
    if not injected:
        return (
            '<section class="panel" data-panel="injected-requirements" '
            'data-injected-count="0"><h2>Injected requirements</h2><div class="body">'
            '<div class="empty">✓ No missing non-functional requirements — every principle '
            "is satisfied. Nothing to inject.</div></div></section>"
        )
    rows = []
    for r in injected:
        cites = "".join(chip(c) for c in r.get("citations", []))
        rows.append(
            f'<div class="inj" data-injected="{esc(r["principle_id"])}" '
            f'data-injected-severity="{esc(r["severity"])}" '
            f'data-injected-citations="{len(r.get("citations", []))}">'
            f'<div class="req"><span class="pid">{esc(r["principle_id"])}</span>'
            f"{esc(r['requirement_text'])}</div>"
            f'<div class="rat">{esc(r["rationale"])}</div>'
            f'<div class="chips">{cites}</div></div>'
        )
    return (
        '<section class="panel" data-panel="injected-requirements" '
        f'data-injected-count="{len(injected)}">'
        "<h2>Injected requirements "
        '<span class="muted">missing NFRs auto-injected at intake</span></h2>'
        f'<div class="body">{"".join(rows)}</div></section>'
    )


def page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{CSS}</style></head><body><div class='wrap'>{body}</div></body></html>"
    )


def _topbar(subtitle: str) -> str:
    return (
        '<div class="topbar"><div class="logo">C3</div>'
        "<div><h1>Architecture &amp; Requirements Validator</h1>"
        f"<p class='sub' style='margin:0'>{esc(subtitle)}</p></div></div>"
    )


def render_case(report: dict) -> str:
    sub = report["submission"]
    body = (
        _topbar("rsk · 12 General Principles · intake gate (R6) · asia-southeast1")
        + render_verdict(report)
        + render_submission(sub)
        + render_findings(report["findings"])
        + render_injected(report["injected_requirements"])
        + "<p class='foot'>Audit-first intake-gate view · synthetic fictional data · "
        "deterministic policy-as-code evaluation</p>"
    )
    return page(f"Intake gate — {sub['id']}", body)


def render_index(data: dict) -> str:
    cards = []
    for c in data["cases"]:
        rep = c["report"]
        sub = rep["submission"]
        passed = rep["passed"]
        cls = "pass" if passed else "fail"
        verdict = "PASS" if passed else "FAIL"
        fails = sum(1 for f in rep["findings"] if f["status"] == "FAIL")
        cards.append(
            f'<a href="arch-case-{esc(c["key"])}.html" data-case="{esc(c["key"])}" '
            f'data-case-verdict="{verdict}" data-case-failing="{fails}">'
            f'<div class="idxcard {cls}">'
            f"<div><div><b>{esc(sub['name'])}</b></div>"
            f"<div class='sub' style='margin:2px 0 0'><span class='mono'>{esc(sub['id'])}</span> · "
            f"region {esc(sub['declared_region'])} · {fails} failing principles</div></div>"
            f'<div class="v">{verdict} ▶</div></div></a>'
        )
    body = (
        _topbar("Demo index · two synthetic intakes · profile=local (offline)")
        + f'<section class="panel" data-panel="demo-cases" data-case-count="{len(data["cases"])}">'
        "<h2>Cases in this demo</h2>"
        f'<div class="body" style="padding:14px 16px"><div class="idx">{"".join(cards)}</div></div></section>'
        "<p class='foot'>Audit-first intake-gate view · synthetic fictional data</p>"
    )
    return page("Intake gate — demo index", body)


def main(json_path: str, out_dir: str) -> None:
    data = json.loads(Path(json_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written = []
    for c in data["cases"]:
        p = out / f"arch-case-{c['key']}.html"
        p.write_text(render_case(c["report"]))
        written.append(p)
    idx = out / "arch-index.html"
    idx.write_text(render_index(data))
    written.append(idx)
    for p in written:
        print("wrote", p)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
