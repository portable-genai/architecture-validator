"""Live, click-through demo server for the C3 intake-gate flow (stdlib HTTP only).

Holds a real :class:`~architecture_validator.domain.services.ValidationService` (built under the
SDK-free ``local`` profile) and runs the *actual* validation one step per click —
intro -> validate the BLOCKED onboarding bot (FAIL + injected requirements) -> validate
the CLEAN policy assistant (PASS) -> done — rendering the audit-first UI at each step.
No Google Cloud, no API key, no extra dependencies.

    PYTHONPATH=src:tests python scripts/arch_demo_server.py [--port 8092]

Then open http://localhost:8092 and click "Next ▶", or drive it with
``scripts/arch_demo_playwright.py`` for a presenter-controlled walkthrough. The demo port
(8092) is deliberately distinct from the FastAPI API port (8088).
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("ARCH_VALIDATOR_PROFILE", "local")

import arch_demo as demo  # noqa: E402  sibling script: reuse the synthetic cases + flow
import render_arch_ui as r  # noqa: E402  sibling script: reuse the audit-first rendering

# The scripted demo steps. Each "Next" performs the action described by ``next``.
STEPS = [
    {
        "key": "intro",
        "label": "Intake gate ready — two synthetic project submissions queued",
        "next": "Validate the customer-facing onboarding bot (us-central1, PII fine-tuning)",
    },
    {
        "key": "blocked",
        "label": "Blocked at intake — multiple principle FAILs, requirements injected",
        "next": "Validate the grounded internal policy assistant (Singapore, fully controlled)",
    },
    {
        "key": "clean",
        "label": "Clears intake — every principle satisfied, nothing to inject",
        "next": None,
    },
]

_CONTROL_CSS = """
.democtl{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;
  margin:-24px -18px 16px;padding:12px 18px;background:#0b101a;color:#fff}
.democtl .lbl{font-size:13px}.democtl .lbl b{color:#90b2ff}
.democtl .spacer{flex:1}
.democtl form{margin:0}
.democtl button{font:inherit;font-size:13px;font-weight:600;border:0;border-radius:7px;
  padding:7px 14px;cursor:pointer}
.democtl .next{background:#3a60f0;color:#fff}.democtl .next:disabled{opacity:.4;cursor:default}
.democtl .restart{background:transparent;color:#a6b6cc;border:1px solid #33445b}
.democtl .verd{font-variant-numeric:tabular-nums;font-size:12px;font-weight:700}
.democtl .verd.pass{color:#34d399}.democtl .verd.fail{color:#fb7185}
"""


class DemoSession:
    """Drives the real intake-gate validation forward one scripted step at a time."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.idx = 0
        self.reports: dict[str, dict] = {}

    @property
    def at_end(self) -> bool:
        return self.idx >= len(STEPS) - 1

    def advance(self) -> None:
        if self.at_end:
            return
        self.idx += 1
        key = STEPS[self.idx]["key"]
        submission = dict(demo.CASES)[key]
        self.reports[key] = demo._validate(submission)

    # -- rendering --------------------------------------------------------- #
    def render(self) -> str:
        key = STEPS[self.idx]["key"]
        if key == "intro":
            html = r.page("Intake gate — ready", self._intro_body())
        else:
            html = r.render_case(self.reports[key])
        return self._inject_controls(html)

    def _intro_body(self) -> str:
        rows = []
        for ckey, sub in demo.CASES:
            label = "expected: BLOCK" if ckey == "blocked" else "expected: CLEAR"
            rows.append(
                f"<li><span class='mono'>{r.esc(sub.id)}</span> — {r.esc(sub.name)} "
                f"<span class='muted'>({r.esc(sub.declared_region)}; {r.esc(label)})</span></li>"
            )
        return (
            r._topbar("rsk · 12 General Principles · intake gate (R6) · asia-southeast1")
            + "<section class='panel'><h2>Two project submissions queued for the gate"
            "<span class='muted'>profile=local · offline</span></h2>"
            "<div class='body' style='padding:14px 16px'>"
            "<ul style='margin:0;padding-left:18px;line-height:1.9'>" + "".join(rows) + "</ul>"
            "<p class='rem' style='color:var(--ink-500);margin-top:10px'>Click "
            "<b>Next ▶</b> to run each submission through the real "
            "<span class='mono'>ValidationService</span>. The verdict and any injected "
            "non-functional requirements are computed deterministically — a FAIL is a normal "
            "cited artifact, not an error.</p></div></section>"
            "<p class='foot'>Audit-first intake-gate view · synthetic fictional data · "
            "deterministic policy-as-code evaluation</p>"
        )

    def _inject_controls(self, html: str) -> str:
        step = STEPS[self.idx]
        nxt = step["next"]
        verd = ""
        key = step["key"]
        if key in self.reports:
            passed = self.reports[key]["passed"]
            cls = "pass" if passed else "fail"
            verd = f"<span class='verd {cls}'>{'PASS' if passed else 'FAIL'}</span>"
        next_btn = (
            f"<form method='post' action='/advance'><button class='next' type='submit'>"
            f"Next ▶ &nbsp;·&nbsp; {r.esc(nxt)}</button></form>"
            if nxt
            else "<button class='next' disabled>Demo complete ✓</button>"
        )
        # The bar carries stable, styling-independent evidence hooks so the served-path
        # self-test can address the presenter control and read the computed verdict without
        # pattern-matching on prose or CSS classes.
        verdict_attr = ""
        if key in self.reports:
            verdict_attr = (
                f" data-step-verdict='{'PASS' if self.reports[key]['passed'] else 'FAIL'}'"
            )
        bar = (
            "<div class='democtl' data-demo='presenter-step'"
            f" data-step='{self.idx}' data-step-count='{len(STEPS)}'"
            f" data-step-key='{r.esc(key)}'"
            f" data-at-end='{str(self.at_end).lower()}'{verdict_attr}>"
            f"<span class='lbl'>Step {self.idx + 1}/{len(STEPS)} — "
            f"<b>{r.esc(step['label'])}</b></span>"
            f"{verd}<span class='spacer'></span>{next_btn}"
            "<form method='post' action='/restart'>"
            "<button class='restart' type='submit'>Restart</button></form>"
            "</div>"
        )
        html = html.replace("</style>", _CONTROL_CSS + "</style>", 1)
        return html.replace("<div class='wrap'>", "<div class='wrap'>" + bar, 1)


class Handler(BaseHTTPRequestHandler):
    session: DemoSession  # set on the server instance below

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, to: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    @property
    def _sess(self) -> DemoSession:
        return self.server.session  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/":
                self._send(self._sess.render())
            elif path == "/state":
                self._send(json.dumps({"step": self._sess.idx}), 200)
            elif path == "/restart":
                # Allowed over GET so the walkthrough can reset with a plain navigation.
                self._sess.reset()
                self._redirect("/")
            else:
                self._send("<h1>404</h1>", 404)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/advance":
                self._sess.advance()
            elif path == "/restart":
                self._sess.reset()
        self._redirect("/")

    def log_message(self, *args: object) -> None:  # quiet console
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Live C3 intake-gate demo server")
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    print(f"C3 intake-gate demo server on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
