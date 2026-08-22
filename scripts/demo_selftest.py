#!/usr/bin/env python3
"""Run the real offline presenter journey and fail if any evidence hook drifts.

Two stages, both against a real run of the intake gate under the SDK-free ``local`` profile:

1. **rendered** - the static case and index pages, checked through their ``data-*`` hooks.
2. **served** - the click-through demo server, walked end to end over real HTTP.

The checks deliberately do not pattern-match on prose or markup shape. Earlier revisions
asserted that ``"synthetic"`` and ``"<section"`` appeared somewhere in each page, which is
satisfied by a page whose panels have silently lost every finding, and which breaks the
moment a caption is reworded. Every figure asserted below is instead **recomputed from the
payload and compared to what the page published**, so a hard-coded or stale number in the
renderer fails rather than passing as a constant.
"""

from __future__ import annotations

import json
import tempfile
import threading
import urllib.request
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

import arch_demo_server as demo_server
from arch_demo import CASES
from arch_demo import main as run_demo
from render_arch_ui import main as render_demo
from render_arch_ui import render_case


class _HookCollector(HTMLParser):
    """Collect every element carrying at least one ``data-*`` attribute."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k: (v or "") for k, v in attrs if k.startswith("data-")}
        if data:
            self.elements.append(data)


def hooks(page: str) -> list[dict[str, str]]:
    parser = _HookCollector()
    parser.feed(page)
    return parser.elements


def one(page: str, key: str, value: str) -> dict[str, str]:
    """The single element whose ``key`` attribute equals ``value``."""
    found = [e for e in hooks(page) if e.get(key) == value]
    assert len(found) == 1, f"expected exactly one [{key}={value}], found {len(found)}"
    return found[0]


def values(page: str, key: str) -> list[str]:
    """Every value of ``key``, in document order."""
    return [e[key] for e in hooks(page) if key in e]


def check_case_page(page: str, report: dict) -> None:
    """A rendered case page must publish exactly what the report computed."""
    submission = report["submission"]
    findings = report["findings"]
    injected = report["injected_requirements"]
    fails = [f for f in findings if f["status"] == "FAIL"]

    verdict = one(page, "data-verdict", "PASS" if report["passed"] else "FAIL")
    assert verdict["data-submission"] == submission["id"]
    assert int(verdict["data-principles-checked"]) == len(findings)
    assert int(verdict["data-fail-count"]) == len(fails)
    assert int(verdict["data-injected-count"]) == len(injected)
    assert verdict["data-review-required"] == str(bool(report["requires_human_review"])).lower()
    # The gate's own invariant: a verdict passes only when nothing failed.
    assert report["passed"] == (not fails)

    panel = one(page, "data-panel", "project-submission")
    assert panel["data-submission-region"] == submission["declared_region"]
    assert int(panel["data-submission-controls"]) == len(submission.get("declared_controls", []))

    panel = one(page, "data-panel", "principle-findings")
    assert int(panel["data-findings-count"]) == len(findings)
    assert int(panel["data-findings-failing"]) == len(fails)
    # Identity and order, not just a count: every principle is rendered, once.
    assert values(page, "data-finding") == [f["principle_id"] for f in findings]
    assert values(page, "data-finding-status") == [f["status"] for f in findings]
    assert values(page, "data-finding-severity") == [f["severity"] for f in findings]
    assert values(page, "data-finding-citations") == [
        str(len(f.get("citations", []))) for f in findings
    ]
    assert all(f["citations"] for f in findings), "an uncited finding is never acceptable"

    panel = one(page, "data-panel", "injected-requirements")
    assert int(panel["data-injected-count"]) == len(injected)
    assert values(page, "data-injected") == [r["principle_id"] for r in injected]
    # Every injected requirement must answer a principle the submission did not satisfy:
    # a requirement injected against an already-satisfied principle is noise, not a gate.
    unsatisfied = {f["principle_id"] for f in findings if f["status"] in {"FAIL", "NEEDS_INFO"}}
    assert {r["principle_id"] for r in injected} <= unsatisfied
    # A clean submission injects nothing at all.
    assert bool(injected) == bool(unsatisfied)


def check_figures_are_computed(report: dict) -> None:
    """Prove the published figures FOLLOW the data instead of being constants.

    Cross-checking a page against the payload cannot catch a hard-coded number that
    currently happens to equal the truth: today there are 12 principles, so a literal
    ``12`` in the renderer passes every comparison. So render a deliberately mutated
    report and require the page to move with it. A constant fails here immediately.
    """
    mutated = json.loads(json.dumps(report))  # deep copy, payload is plain JSON
    dropped = mutated["findings"].pop()
    mutated["injected_requirements"] = [
        r for r in mutated["injected_requirements"] if r["principle_id"] != dropped["principle_id"]
    ]
    page = render_case(mutated)

    fails = [f for f in mutated["findings"] if f["status"] == "FAIL"]
    verdict = one(page, "data-verdict", "PASS" if mutated["passed"] else "FAIL")
    assert (
        int(verdict["data-principles-checked"])
        == len(mutated["findings"])
        != len(report["findings"])
    ), "the principles-checked figure did not follow the data; it is hard-coded"
    assert int(verdict["data-fail-count"]) == len(fails)
    assert int(verdict["data-injected-count"]) == len(mutated["injected_requirements"])

    panel = one(page, "data-panel", "principle-findings")
    assert int(panel["data-findings-count"]) == len(mutated["findings"]), (
        "the findings-count figure is hard-coded"
    )
    assert int(panel["data-findings-failing"]) == len(fails)
    assert values(page, "data-finding") == [f["principle_id"] for f in mutated["findings"]]

    panel = one(page, "data-panel", "injected-requirements")
    assert int(panel["data-injected-count"]) == len(mutated["injected_requirements"]), (
        "the injected-count figure is hard-coded"
    )


def check_rendered(payload: dict, out: Path) -> None:
    """Stage 1: the static pages the demo ships."""
    by_key = {case["key"]: case["report"] for case in payload["cases"]}
    assert len(payload["cases"]) == len(CASES) == 2
    assert by_key["blocked"]["passed"] is False
    assert by_key["clean"]["passed"] is True
    for report in by_key.values():
        assert report["requires_human_review"] is True

    expected = {"arch-index.html", "arch-case-blocked.html", "arch-case-clean.html"}
    assert expected <= {path.name for path in out.iterdir()}

    for key, report in by_key.items():
        page = (out / f"arch-case-{key}.html").read_text(encoding="utf-8")
        check_case_page(page, report)
    # The blocked case has the richest data, so mutate that one to prove the
    # figures are computed rather than hard-coded constants that merely match today.
    check_figures_are_computed(by_key["blocked"])

    # The index must agree with the case pages it links to.
    index = (out / "arch-index.html").read_text(encoding="utf-8")
    panel = one(index, "data-panel", "demo-cases")
    assert int(panel["data-case-count"]) == len(payload["cases"])
    assert values(index, "data-case") == [c["key"] for c in payload["cases"]]
    assert values(index, "data-case-verdict") == [
        "PASS" if c["report"]["passed"] else "FAIL" for c in payload["cases"]
    ]
    assert values(index, "data-case-failing") == [
        str(sum(1 for f in c["report"]["findings"] if f["status"] == "FAIL"))
        for c in payload["cases"]
    ]


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - fixed localhost
        return response.read().decode("utf-8")


def _post(url: str) -> str:
    request = urllib.request.Request(url, data=b"", method="POST")  # noqa: S310
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        return response.read().decode("utf-8")


def check_served(base: str, by_key: dict[str, dict]) -> None:
    """Stage 2: walk the presenter server over HTTP, step by step."""
    steps = [s["key"] for s in demo_server.STEPS]
    seen = []
    for position, key in enumerate(steps):
        page = _get(f"{base}/")
        bar = one(page, "data-demo", "presenter-step")
        assert int(bar["data-step"]) == position, f"step {position}: bar says {bar['data-step']}"
        assert int(bar["data-step-count"]) == len(steps)
        assert bar["data-step-key"] == key
        assert bar["data-at-end"] == str(position == len(steps) - 1).lower()
        # The server's own state endpoint must agree with what it published.
        assert json.loads(_get(f"{base}/state"))["step"] == position

        if key == "intro":
            # The intro screen is a queue, not a verdict: no case panels yet.
            assert "data-step-verdict" not in bar
            assert not [e for e in hooks(page) if "data-verdict" in e]
        else:
            # Each validated step must render the real case page, live, and its
            # served verdict must match the report the same run computed offline.
            report = by_key[key]
            expected = "PASS" if report["passed"] else "FAIL"
            assert bar["data-step-verdict"] == expected, f"{key}: served verdict disagrees"
            check_case_page(page, report)
        seen.append(bar["data-step-key"])
        if position < len(steps) - 1:
            _post(f"{base}/advance")
    assert seen == steps, f"presenter walk visited {seen}"

    # Advancing past the last step is a no-op, not a crash or a wrap-around.
    _post(f"{base}/advance")
    bar = one(_get(f"{base}/"), "data-demo", "presenter-step")
    assert int(bar["data-step"]) == len(steps) - 1
    assert bar["data-at-end"] == "true"

    # Restart returns the presenter to the intro, with the verdicts cleared.
    _post(f"{base}/restart")
    page = _get(f"{base}/")
    bar = one(page, "data-demo", "presenter-step")
    assert int(bar["data-step"]) == 0
    assert bar["data-step-key"] == steps[0]
    assert not [e for e in hooks(page) if "data-verdict" in e]


def _serve() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    """Boot the real demo server on an ephemeral port, exactly as ``make demo-server`` does."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), demo_server.Handler)
    server.session = demo_server.DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rsk3-demo-") as tmp:
        out = Path(tmp)
        payload_path = out / "journey.json"
        run_demo(str(payload_path))
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        render_demo(str(payload_path), str(out))
        check_rendered(payload, out)
        print("demo self-test: rendered pages PASS")

        by_key = {case["key"]: case["report"] for case in payload["cases"]}
        server, thread, base = _serve()
        try:
            check_served(base, by_key)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        print("demo self-test: served presenter walkthrough PASS")

    print("demo self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
