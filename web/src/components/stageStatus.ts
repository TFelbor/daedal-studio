/**
 * Where a phase is, as the pipeline reports it — nothing finer.
 *
 * Its own module rather than a second export from `StageState.tsx`, for the reason
 * `promptLimits.ts` is one: a file that exports both a component and a function loses
 * fast refresh for the component.
 */
export type StageStatus = 'pending' | 'running' | 'done';

/**
 * A pipeline phase status (`pending` / `running` / `complete` / `error`, or the job
 * statuses the blueprint frame is handed) collapsed onto the three states a stage can
 * draw. An errored phase reads as `pending` here on purpose: every host that can show
 * an error already has its own branch for it, and a stage must never be the thing that
 * reports a failure as work in progress.
 */
export function stageStatus(status: string | null | undefined): StageStatus {
  if (status === 'running') return 'running';
  if (status === 'complete' || status === 'completed' || status === 'done') return 'done';
  return 'pending';
}
