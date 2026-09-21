# `docs/audits/` — dated audit runs

One file per run **that found something**: `YYYY-MM-DD-<kind>-licence.md` for a licence
audit, and the same date convention for any other recurring review that lands here.

A run whose digest matches the newest existing note writes no file at all, and says so
(`[licence-report] no audit note: the digest is identical to …`). This directory is
therefore a record of the dates on which the tree *moved*, not of the dates on which it
was looked at — the run log is the record of the looking. It used to be one file per
run unconditionally, which is how thirteen notes accumulated in three weeks, several of
them byte-identical apart from the date, and how `licence-data.yml`'s "nothing changed,
do not commit" guard came to be unreachable: a new date is a new path, so the staged
diff was never empty. See `audit_note_would_repeat` in
[`infra/scripts/licence_report.py`](../../infra/scripts/licence_report.py).

A note that already exists is always refreshed in place, whatever its digest says — a
same-day rerun should update the commit sha it records, and the file may carry a
person's reasoning that only the generated block may be written over.

The point of the directory is **deltas**. An audit that starts from scratch every week
re-derives the same forty findings, and the one new thing is indistinguishable from the
thirty-nine already accepted. Starting from "compare against `docs/audits/`" turns the
same routine into "what changed since the last run", which is the only question with a
short answer.

## The external watch, which is not generated

`YYYY-MM-DD-external-licence.md` is a second, **entirely hand-written** series, and it
has no generated block at all. It covers what `licence-data.yml` and
`licence_report.py` structurally cannot reach: vendor terms of service, upstream
relicensing, and whether the previous run's blockers are still alive. Its filename is
deliberately outside `_AUDIT_NAME_RE`
([`infra/scripts/licence_report.py`](../../infra/scripts/licence_report.py)), so the
generated writer never diffs against it and never writes into it.

Findings carry an **E-number**, and *those numbers are permanent*: a later run keeps the
number an item was first given and takes fresh numbers for genuinely new items. This is
the one rule the series has and it has already been broken once — 2026-09-21 renumbered
from scratch over 2026-09-19's set, so "E1" named two different findings in consecutive
reports and a cross-reference in `docs/deferred-legal-tasks.md` resolved to the wrong
one. That report carries the correction and the mapping at its head. **Before numbering
anything, read the previous external watch's § 6.**

`vendor-terms/<vendor>-<date>.md` holds the summarised text of a third party's terms as
read on that date, with retrieval dates against each clause. One file per reading, never
edited in place: the whole value is being able to say what a vendor's terms said on a
day, which is also why a later reading gets a new file rather than an update.

## The shape of a file

Each file has two halves and they belong to different authors.

* **The generated block**, between `<!-- generated:begin -->` and `<!-- generated:end -->`,
  is written by `infra/scripts/licence_report.py` from `licenses/report.json`. It carries
  counts, the delta against the previous dated file, the findings table, and a
  machine-readable `digest` fence. **Do not edit it** — it is rewritten in place on the
  next run.
* **Everything outside that block is preserved.** That is where judgement goes: whether a
  flag matters, what was decided, what was deferred and to when. A scanner cannot produce
  any of it, and regenerating the file must not destroy it — which is why the writer
  replaces only the marked block rather than the whole file.

## The digest

```json digest
{ "packages": …, "by_severity": {…}, "findings": ["severity:source:package@version:licence", …] }
```

The next run reads the newest *other* dated file's digest and diffs against it. Two
things are deliberately excluded: the generation timestamp and the commit sha, so a run
that found nothing new produces a byte-identical digest, and "nothing changed" is
visible as an empty delta rather than inferred from reading two tables side by side.

Aggregated OS-layer rows are keyed by class and **count**, not by which packages were in
the set — a base-image bump that swaps which GPL packages are present without changing
how many is not a new finding.

## Running one

```bash
make licence-audit     # writes docs/audits/<today>-licence.md from licenses/
```

CI does this on the 1st and the 15th, and on a manual run
(`.github/workflows/licence-data.yml`). The raw trees under
[`licenses/`](../../licenses/README.md) are the input; that directory's README explains
where each file comes from and which trees CI cannot produce.

## What is *not* here

The reasoned licence position — per component, with the obligations that attach — is
[`THIRD-PARTY-NOTICES.md`](../../THIRD-PARTY-NOTICES.md), and it is a living document
rather than a dated snapshot. An audit run here either confirms it or names something it
does not yet cover; when it names something, **the notices file is what gets updated**,
and the audit note records that it was.
