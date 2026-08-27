# `docs/audits/` — dated audit runs

One file per run: `YYYY-MM-DD-<kind>-licence.md` for a licence audit, and the same date
convention for any other recurring review that lands here.

The point of the directory is **deltas**. An audit that starts from scratch every week
re-derives the same forty findings, and the one new thing is indistinguishable from the
thirty-nine already accepted. Starting from "compare against `docs/audits/`" turns the
same routine into "what changed since the last run", which is the only question with a
short answer.

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

CI does this on every push to `main` and on the weekly schedule
(`.github/workflows/licence-data.yml`). The raw trees under
[`licenses/`](../../licenses/README.md) are the input; that directory's README explains
where each file comes from and which trees CI cannot produce.

## What is *not* here

The reasoned licence position — per component, with the obligations that attach — is
[`THIRD-PARTY-NOTICES.md`](../../THIRD-PARTY-NOTICES.md), and it is a living document
rather than a dated snapshot. An audit run here either confirms it or names something it
does not yet cover; when it names something, **the notices file is what gets updated**,
and the audit note records that it was.
