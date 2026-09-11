/**
 * The disclosure wording for EU AI Act Art. 50(1), worded once.
 *
 * Art. 50(1) applies from 2 August 2026 and requires the *interface* to tell a
 * natural person they are interacting with an AI system — the Commission's May 2026
 * guidelines say a line in the T&Cs is not enough, and the Digital Omnibus grace
 * period to 2 December 2026 reaches only systems placed on the market before that
 * date, so this one gets none. Wording approved by the owner on 2026-09-09 (issue
 * #78) and used verbatim.
 *
 * Two halves, and the load-bearing one is the first: **a person's prompt is read by
 * an AI system**, which is true on every path this product has — FLUX reads it on the
 * generative path today, and the extractor will read it on the parametric one. The
 * tail describes the parametric pipeline the whole UI was moved onto ahead of the
 * engine (see the note in `pipeline.ts`, and the Composer blurb that already says
 * "your words become a structured spec"): it is literal for a `--spec` job, where
 * `pythonsrc/organizer/` compiles the geometry deterministically, and it is the
 * product's committed vocabulary rather than a claim about which model ran on a
 * given job — `generation_model` and `blueprint_model` are what record that. When
 * the composer can build a spec, the tail becomes literal everywhere; until then do
 * not read it as a per-job statement.
 */
export const AI_SYSTEM_NOTICE =
  'Your prompt is read by an AI system that turns it into a parametric spec; ' +
  'the geometry itself is computed, not generated.';

/**
 * The same disclosure in fewer words, for the running view's Composer stage — where
 * the extracted spec is shown. Kept here rather than in `NewJob.tsx` so the two
 * places the product says this cannot drift apart.
 */
export const AI_SYSTEM_NOTICE_SHORT =
  'Your prompt is read by an AI system; the geometry itself is computed, not generated.';

/**
 * The one line the product says before anyone types a prompt.
 *
 * Three claims now, and all of them have to be there. **AI disclosure**, because
 * Art. 50(1) puts the duty on the interface (`AI_SYSTEM_NOTICE` above); it leads,
 * because it is the one a regulator reads and the one that has to be found before
 * the first interaction rather than after it. **Rights**, because the thing this app
 * does is manufacture and hand over a physical object — which is direct
 * infringement analysis if the object reproduces a protected character, with no
 * intermediary shelter available and no private-use exception reaching a paid
 * service. **Retention**, because the prompt is stored verbatim and permanently on
 * `print_job.prompt`, the engineered variant beside it, and whatever the pipeline
 * produced in the job's output directory. "What it produces" rather than "the
 * image": the artifact is a blueprint image today and a spec plus a mesh once the
 * parametric engine lands, and the sentence has to stay true across that change.
 *
 * Shared rather than repeated so the landing composer, the inline "New job"
 * composer and the zoomed field cannot end up telling people different things.
 *
 * Styled with the global `hint` class and **never** `notice`: the latter is the
 * failure treatment (bad-line, bad-tint, bad-ink), and rendering a neutral
 * statement in the app's error colour is the same class of mistake as captioning a
 * fixture blueprint as drawn from the prompt.
 */
export function PromptNotice({ className }: { className?: string }) {
  return (
    <p className={className ? `hint ${className}` : 'hint'}>
      {AI_SYSTEM_NOTICE} Functional geometry only — we never generate or scrape art, and
      you must hold the right to whatever you describe. Your prompt and what it produces
      are kept with the job.
    </p>
  );
}
