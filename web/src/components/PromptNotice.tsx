/**
 * The one line the product says before anyone types a prompt.
 *
 * Two claims, and both have to be there. **Rights**, because the thing this app
 * does is manufacture and hand over a physical object — which is direct
 * infringement analysis if the object reproduces a protected character, with no
 * intermediary shelter available and no private-use exception reaching a paid
 * service. **Retention**, because the prompt is stored verbatim and permanently on
 * `print_job.prompt`, the engineered variant beside it, and the generated image in
 * the job's output directory.
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
      Original designs only — you must hold the right to whatever you describe.
      Your prompt and the image it produces are kept with the job.
    </p>
  );
}
