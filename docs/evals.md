# How the architecture validator is evaluated

Read this page if you decide what this service is allowed to approve. The metrics, the bars and
the corpora below are generated from the artifacts that actually gate the build, so they cannot
drift from what runs: `make evals-doc-check` fails the build when this page and those artifacts
disagree.

## How to run it

```sh
make eval              # both families, offline, no credentials
make evals-doc-check   # this page is still true
```

`make check` runs both on every change.

## Two families, one run, and no shared bars

Architecture review and data-residency scanning are scored in the same run and reported in the
same table, and they share metric NAMES: both have a `citation_accuracy` and a `safety`. They are
different questions with the same words, so the residency rubrics live in their own directory and
the runner narrows to a group before reading a bar. Merging them would silently give a design
review the residency family's threshold.

This is also why `agent-eval-kit` keys rubrics by group and metric rather than by metric alone.
Keyed by name, whichever file sorted last won and the other family's rubric vanished from the
tree while still sitting on disk looking authoritative.

## The residency corpus grew, and the reason is arithmetic

Every violating scan carried exactly one violation kind. Two things went unmeasured: whether the
scanner reports the second problem once it has reported the first, and whether the recall bar
meant anything. Nine expected kinds cannot express a 0.90 bar, which tolerates one miss only over
ten, so the bar was arithmetically identical to 1.0.

Three multi-violation resources and one more clean one are added.

## What is measured, and against what bar

Two families, scored in one run and reported in one table. They share metric NAMES and
do not share bars, which is why the residency rubrics live in their own directory: a
design review and a data-residency scan are different questions with the same words.

| Family | Metric | Bar | Denominator | What it measures |
|---|---|---|---|---|
| architecture | `citation_accuracy` | 0.9 | a rate; needs 10 positives | Fraction of findings and injected requirements that carry at least one citation, averaged over the golden set. Must be at least 0.90 to promote. |
| architecture | `injection_recall` | 0.8 | a rate; needs 5 positives | Fraction of the expected-to-be-injected principles for which the validator produced an injected requirement, averaged over the golden set. Must be at least 0.80 to promote. |
| architecture | `principle_accuracy` | 0.9 | a rate; needs 10 positives | Fraction of principles whose PASS/FAIL verdict matches the golden expectation, averaged over the golden submission set. Must be at least 0.90 to promote. |
| architecture | `safety` | 1 | a rate; needs 0 positives | Fraction of golden examples where the validator did not pass a project that was expected to fail. Must be at least 0.99 to promote (the gate must fail closed). |
| residency | `citation_accuracy` | 0.9 | a rate; needs 10 positives | Per-example correctness of the citation set on emitted violations: every violation cites a residency principle (P-01 / P-03 / P-10) and the relevant regulator. Averaged over the dataset. |
| residency | `detection_recall` | 0.9 | a rate; needs 10 positives | Fraction of the planted violation kinds the detector correctly finds per example, averaged over the golden set. A planted violation that is missed drops the score. |
| residency | `precision` | 0.9 | a rate; needs 10 positives | No false-positive violations on clean, compliant resources. A clean resource that is flagged drops precision; in-country resources with CMEK, VPC-SC and public access prevented must produce zero violations. |
| residency | `safety` | 1 | a rate; needs 0 positives | The gate verdict (PASS/FAIL) matches the golden expectation for every example: a clean estate never gates FAIL spuriously, and a violating estate never passes. A single mismatch drops the metric below 0.99. |

## What is exercised

- **8 golden submissions** in
  `eval/datasets/golden_submissions.jsonl`, with the principles a reviewer expected to
  fail and the requirements they expected to be injected.
- **18 golden residency scans** in `eval/datasets/golden_scans.jsonl`,
  carrying **15 expected violation kinds**. That count is what
  `residency_detection_recall` is measured over, not the scan count.
- **3 of the scans carry more than one violation at once.** Every violating scan
  used to carry exactly one, so nothing measured whether the scanner reports the second
  problem once it has reported the first.
- **6 clean scans**, which is what a false positive can fire on.

## How a metric is prevented from being decoration

1. **The bars are read from the rubrics, per family, in both directions.** The two `THRESHOLDS`
   dicts are gone, and `assert_covers` runs against the group rather than the whole tree, so a
   metric with no reviewed bar and a bar that names no metric both fail the build in the family
   they belong to.
2. **The denominator rule is asserted against what actually divides each rate**, and that is the
   case count for none of them: principle accuracy over the principles evaluated, citation
   accuracy over the findings and injected requirements produced, injection recall over the
   principles a reviewer expected injected, residency recall over the labelled violation kinds.

## What is NOT measured here

- **A real model's words.** The metrics score deterministic policy evaluation against a
  deterministic fake model adapter.
- **Precision of the architecture findings.** `principle_accuracy` scores both directions per
  principle, but there is no separate false-positive metric over a corpus of clean submissions.
- **Production traffic.** Everything here is a golden set. Nothing samples live requests.
