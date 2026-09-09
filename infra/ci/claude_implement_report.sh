#!/usr/bin/env bash
#
# Leave a claude-implement run where a person can find it.
#
# The model step used to be the last step in `.github/workflows/claude-implement.yml`
# that did anything. When it ran out of turns — issue #60, 81 turns, nothing pushed —
# the job went red in the Actions tab and that was the entire report: no branch, no
# pull request, no comment on the issue, no transcript. Whoever labelled the issue
# found out by going to look.
#
# This runs after the model with `if: always()` and turns whatever the run left into
# something with a URL:
#
#   uncommitted edits            -> one `WIP:` commit, clearly marked as the workflow's
#   commits origin does not have -> pushed
#   commits and no pull request  -> a *draft* pull request, saying why it is a draft
#   commits and a pull request   -> a comment on it when the run failed
#   nothing committed            -> a comment on the issue saying so, and why
#
# A person can then finish it, resume it with one `@claude please continue` comment
# (claude-implement.yml's `fix` job answers those on any open pull request), or throw
# it away. What they cannot do is wonder.
#
# Inputs, all from the environment:
#
#   MODE            implement | fix                        default: implement
#   ISSUE_NUMBER    the issue being implemented            implement mode
#   ISSUE_TITLE     its title, for a draft's title         implement mode
#   PR_NUMBER       the pull request being fixed           fix mode
#   BRANCH          the working branch                     default: the current branch
#   BASE_BRANCH     what pull requests target              default: main
#   RISK_LABEL      a `risk:*` label for a pull request this script opens (optional)
#   CONCLUSION      the model step's outcome: success | failure | cancelled | empty
#   EXECUTION_FILE  the action's execution_file output; may be absent
#   RUN_URL         a link to the run
#   GH_TOKEN        what `gh` authenticates with — the Claude App's token when the
#                   action produced one, so a draft it opens is the app's, which is
#                   what lets claude-review's fix loop ask for changes on it
#
# The exit status is always 0. The model step has already coloured the job; a
# reporting error on top of a real failure must not replace it in the summary.
#
# Tested by tests/test_claude_implement_report.py against a bare repository and a
# fake `gh`. Kept in the repository rather than heredoc'd into the workflow so that it
# is reviewable and so the thing CI runs is the same thing the tests run.

set -u
set -o pipefail

MODE="${MODE:-implement}"
BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
BASE_BRANCH="${BASE_BRANCH:-main}"
CONCLUSION="${CONCLUSION:-}"
EXECUTION_FILE="${EXECUTION_FILE:-}"
RUN_URL="${RUN_URL:-}"
RISK_LABEL="${RISK_LABEL:-}"
ISSUE_NUMBER="${ISSUE_NUMBER:-}"
ISSUE_TITLE="${ISSUE_TITLE:-}"
PR_NUMBER="${PR_NUMBER:-}"

log() { echo "report: $*" >&2; }

# One clause describing how the model step ended, read from the result message in the
# execution file: "error_max_turns after 81 turns, 1 permission denial". The action
# hides the turns from the log, so this is the only place the figure exists.
reason() {
  if [ -n "$EXECUTION_FILE" ] && [ -f "$EXECUTION_FILE" ]; then
    local r
    r=$(jq -r '
      ([.[] | select(.type == "result")] | last) // empty
      | ((.permission_denials // []) | length) as $d
      | "\(.subtype) after \(.num_turns) turns"
        + (if $d > 0 then ", \($d) permission denial" + (if $d > 1 then "s" else "" end) else "" end)
        + (if ((.errors // []) | length) > 0 then " — " + ((.errors[0] | tostring)[0:240]) else "" end)
    ' "$EXECUTION_FILE" 2>/dev/null) || r=""
    if [ -n "$r" ]; then
      printf '%s' "$r"
      return
    fi
  fi
  printf '%s' "the action step did not report a result"
}

# The result message's subtype alone — `error_max_turns`, `error_during_execution`, `success`
# — or `none` when the action left no result. It rides in the marker so claude-resume can
# tell a budget failure (do not retry) from a transient one (retry) without parsing prose.
subtype() {
  if [ -n "$EXECUTION_FILE" ] && [ -f "$EXECUTION_FILE" ]; then
    local t
    t=$(jq -r '(([.[] | select(.type == "result")] | last) // empty) | .subtype // empty' "$EXECUTION_FILE" 2>/dev/null) || t=""
    if [ -n "$t" ]; then printf '%s' "$t"; return; fi
  fi
  printf 'none'
}

# The markers are the protocol between this script and .github/workflows/claude-resume.yml:
#   safety-net  — on every draft body and comment this script writes, with the subtype
#   finished    — a run succeeded while a safety-net draft existed; the loop stops here
#   resume      — written by claude-resume when it re-dispatches (counted for the cap)
marker()   { printf '<!-- claude-implement-safety-net subtype=%s -->' "$(subtype)"; }
FINISHED_MARKER='<!-- claude-implement-finished -->'

# What happens next, said once and honestly: a budget failure repeats itself on retry; a
# transient one — the subscription's usage wall above all — is what claude-resume exists for.
retry_note() {
  if [ "$(subtype)" = "error_max_turns" ]; then
    printf 'This is **not retried automatically**: the turn budget is the cap on one attempt, and retrying repeats it. Split the issue, switch it to `tier:fable-plan`, or spend another attempt deliberately with the resume comment above.'
  else
    printf 'If this was the subscription'"'"'s usage limit or another transient error, the `claude-resume` workflow re-dispatches this issue within about two hours, up to 3 attempts, unless a person comments on the pull request first.'
  fi
}

ensure_identity() {
  git config user.name >/dev/null 2>&1 || git config user.name "claude-implement[bot]"
  git config user.email >/dev/null 2>&1 || git config user.email "claude-implement@users.noreply.github.com"
}

# Uncommitted work is the likeliest thing a run out of turns leaves behind, and the
# easiest to lose: the runner is gone a minute after this script. `git add -A` honours
# .gitignore, so `data/`, `pythonsrc/config.py` and `node_modules/` stay out.
commit_leftovers() {
  if [ -n "$(git status --porcelain)" ]; then
    ensure_identity
    git add -A
    if git commit -q -m "WIP: uncommitted changes when the claude-implement run ended" \
        -m "Committed by the workflow, not by the model, so that they were not lost with the runner. Review before keeping."; then
      log "committed leftover changes as a WIP commit"
    fi
  fi
}

# Push what origin does not have: commits past origin/BRANCH when the branch exists
# there, otherwise everything past the base branch.
push_branch() {
  git fetch -q origin --prune 2>/dev/null || true
  local upstream="origin/$BRANCH"
  git rev-parse --verify -q "$upstream" >/dev/null || upstream="origin/$BASE_BRANCH"
  local unpushed
  unpushed=$(git rev-list --count "$upstream..HEAD" 2>/dev/null || echo 0)
  if [ "$unpushed" -gt 0 ]; then
    if git push -q -u origin "HEAD:refs/heads/$BRANCH"; then
      log "pushed $unpushed commit(s) to $BRANCH"
    else
      log "could not push $BRANCH; the commits are only on this runner"
      return 1
    fi
  fi
}

ahead_of_base() {
  git rev-list --count "origin/$BASE_BRANCH..HEAD" 2>/dev/null || echo 0
}

comment_issue() {
  if [ -z "$ISSUE_NUMBER" ]; then
    log "no issue number to report to; the report would have been: $1"
    return
  fi
  gh issue comment "$ISSUE_NUMBER" --body "$1" >/dev/null || log "could not comment on issue #$ISSUE_NUMBER"
}

comment_pr() {
  gh pr comment "$1" --body "$2" >/dev/null || log "could not comment on pull request #$1"
}

resume_hint() {
  local target="${ISSUE_NUMBER:+ implementing #$ISSUE_NUMBER}"
  printf 'To resume where it stopped, comment on the pull request:\n\n    @claude please continue%s: read the issue, the Plan comment if there is one, and the diff so far, then finish the remaining acceptance criteria and mark the pull request ready for review.\n' "$target"
}

transcript_hint() {
  printf 'The transcript is attached to the run as an artifact. Run: %s' "$RUN_URL"
}

implement_mode() {
  local why
  why=$(reason)
  commit_leftovers

  local ahead
  ahead=$(ahead_of_base)
  if [ "$ahead" -eq 0 ]; then
    if [ "$CONCLUSION" = "success" ]; then
      comment_issue "$(printf '**claude-implement finished without changing any file** (%s), so there is nothing to open a pull request from. Read the transcript before re-running: the issue may already be done, or may not say what to do.\n\n%s' "$why" "$(transcript_hint)")"
    else
      comment_issue "$(printf '**claude-implement did not open a pull request for this issue.** The run ended with %s, and nothing was committed on `%s`.\n\nTo try again, remove and re-apply the `tier:*` label, or run the `claude-implement` workflow by hand with `issue_number=%s`. If the issue is large — several modules, a decision to make first, a Size L — split it or switch it to `tier:fable-plan`; see docs/PIPELINE.md. (With nothing committed there is no draft for `claude-resume` to pick up; re-label or re-run by hand.)\n\n%s' "$why" "$BRANCH" "${ISSUE_NUMBER:-N}" "$(transcript_hint)")"
    fi
    return
  fi

  push_branch || true

  local prs pr_number pr_url
  prs=$(gh pr list --head "$BRANCH" --state open --json number,url,isDraft,body) || prs="[]"
  pr_number=$(printf '%s' "$prs" | jq -r '.[0].number // empty' 2>/dev/null) || pr_number=""
  pr_url=$(printf '%s' "$prs" | jq -r '.[0].url // empty' 2>/dev/null) || pr_url=""
  pr_is_safety_net_draft=$(printf '%s' "$prs" | jq -r '.[0] | if (.isDraft == true and ((.body // "") | contains("<!-- claude-implement-safety-net"))) then "yes" else "no" end' 2>/dev/null) || pr_is_safety_net_draft="no"

  if [ -n "$pr_number" ]; then
    if [ "$CONCLUSION" = "success" ]; then
      # A finished run on a draft this script opened: the draft was waiting for exactly
      # this. Marking it ready hands it to claude-review; the finished marker stops
      # claude-resume. A draft the model or a person opened is theirs to promote.
      if [ "$pr_is_safety_net_draft" = "yes" ]; then
        gh pr ready "$pr_number" >/dev/null || log "could not mark #$pr_number ready"
        comment_pr "$pr_number" "$(printf '%s\n**The resumed claude-implement run finished** (%s) and this pull request is now ready for review. Read the checklist in the description against the issue before merging.\n\n%s' "$FINISHED_MARKER" "$why" "$(transcript_hint)")"
      fi
      return 0
    fi
    comment_pr "$pr_number" "$(printf '%s\n**The claude-implement run behind this pull request ended with %s.** Everything committed when it ended has been pushed here, including a `WIP:` commit of uncommitted changes if there is one. Treat the diff as unfinished.\n\n%s\n%s\n\n%s' "$(marker)" "$why" "$(resume_hint)" "$(retry_note)" "$(transcript_hint)")"
    return
  fi

  # Commits and no pull request: open a draft, as the workflow, and say so.
  local title body url
  if [ "$CONCLUSION" = "success" ]; then
    title="$ISSUE_TITLE"
    body=$(printf 'Closes #%s\n\n%s\n**Opened by the claude-implement workflow, not by the model.** The run finished (%s) and pushed its work but never opened a pull request, so it is here as a draft. Read the diff against the acceptance criteria, then mark it ready for review or hand it back with a comment.\n\n%s\n%s' "$ISSUE_NUMBER" "$(marker)" "$why" "$(resume_hint)" "$(transcript_hint)")
  else
    title="WIP: $ISSUE_TITLE"
    body=$(printf 'Closes #%s\n\n%s\n**Opened by the claude-implement workflow, not by the model.** The implementation run ended with %s. This branch holds everything that was committed when it ended — including a `WIP:` commit of uncommitted changes, if there is one — and none of it has been reviewed or claimed finished.\n\n%s\n%s\n\nTo start over instead, close this pull request, delete the branch, and re-apply the tier label to the issue (or run the `claude-implement` workflow by hand with `issue_number=%s`).\n\n%s' "$ISSUE_NUMBER" "$(marker)" "$why" "$(resume_hint)" "$(retry_note)" "$ISSUE_NUMBER" "$(transcript_hint)")
  fi

  # `${arr[@]+"${arr[@]}"}` is the empty-array expansion that bash 3.2 accepts under
  # `set -u` — the runner's bash 5 does not need it, a developer's macOS /bin/bash does.
  local -a label_args=()
  [ -n "$RISK_LABEL" ] && label_args=(--label "$RISK_LABEL")
  if url=$(gh pr create --draft --head "$BRANCH" --base "$BASE_BRANCH" --title "$title" --body "$body" ${label_args[@]+"${label_args[@]}"}); then
    log "opened draft pull request $url"
  else
    log "could not open a pull request for $BRANCH"
    url="the branch \`$BRANCH\`"
  fi

  if [ "$CONCLUSION" = "success" ]; then
    comment_issue "$(printf 'claude-implement finished (%s) without opening a pull request; the workflow opened its work as a draft: %s. Review it and mark it ready, or comment on it to hand it back.\n\n%s' "$why" "$url" "$(transcript_hint)")"
  else
    comment_issue "$(printf '**claude-implement did not finish this issue.** The run ended with %s. What it committed is on %s as a draft pull request; the resume and restart instructions are in its description.\n\n%s' "$why" "$url" "$(transcript_hint)")"
  fi
}

fix_mode() {
  local why
  why=$(reason)
  commit_leftovers
  push_branch || true
  [ "$CONCLUSION" = "success" ] && return 0
  if [ -z "$PR_NUMBER" ]; then
    log "fix mode without PR_NUMBER; nowhere to report: $why"
    return
  fi
  comment_pr "$PR_NUMBER" "$(printf '%s\n**The claude-implement fix run on this pull request ended with %s.** Everything committed when it ended has been pushed, including a `WIP:` commit of uncommitted changes if there is one; the review comments it was answering may be only partly addressed.\n\n%s\n%s' "$(marker)" "$why" "$(resume_hint)" "$(transcript_hint)")"
}

main() {
  case "$MODE" in
    implement) implement_mode ;;
    fix) fix_mode ;;
    *) log "unknown MODE '$MODE'; nothing reported" ;;
  esac
}

main || log "reporting hit an error; the model step's own status stands"
exit 0
