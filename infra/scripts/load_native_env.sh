# infra/scripts/load_native_env.sh
#
# Source this — do not execute it:
#   . infra/scripts/load_native_env.sh
#
# Why this is an allowlist and not `set -a; . ./.env`
# ---------------------------------------------------
# `.env` is the *containers'* environment. Compose hands it to services whose
# filesystem is the image's, so it legitimately holds absolute container paths:
#
#   FLUX_MODEL_PATH=/models/flux
#   HF_HOME=/models/hf_cache
#
# Exporting one of those into a process running natively on macOS points it at a
# directory that does not exist, or at `/`, which is read-only — a crash before
# uvicorn ever binds a port.
#
# `TELEMETRY_DB_PATH=/app/telemetry/telemetry.db` used to be the worst example, and
# it is no longer in `.env` at all: the database is now the single host file
# `~/.ds-mvp/telemetry.db`, bind-mounted into the containers, so no execution mode
# needs the variable. It was not just a crash risk — while it was set, container
# runs and native runs used two *different* databases and nothing said so. See
# "One database" in CLAUDE.md.
#
# So only keys that mean the same thing on both sides of the container boundary
# are lifted across — credentials and backend selection. Every path is left at its
# native default, which is what `config.py` and `telemetry/db.py` already compute
# from the repo root and `$HOME`.
#
# Adding a key here is a claim that it is host-agnostic. If it names a filesystem
# location, it is not.
#
# Keys are read from a here-document rather than iterated out of a variable
# because `for k in $VAR` splits on whitespace in sh/bash but *not* in zsh, and
# this file is sourced from both `make` (/bin/sh) and interactive shells. The
# here-doc redirect also keeps the loop in the current shell — piping into `while`
# would run it in a subshell and every export would be discarded.

if [ -f .env ]; then
    while IFS= read -r _ds_key; do
        [ -n "$_ds_key" ] || continue
        # `tail -1` so a duplicated key behaves the way a shell assignment would:
        # the last occurrence wins, rather than silently concatenating.
        _ds_val=$(sed -n "s/^${_ds_key}=//p" .env | tail -1)
        if [ -n "$_ds_val" ]; then
            export "${_ds_key}=${_ds_val}"
        fi
    done <<'DS_NATIVE_ENV_KEYS'
HF_TOKEN
HUGGINGFACE_HUB_TOKEN
PIXAZO_API_KEY
# The kill switch must travel with the key that enables spending. Carrying
# PIXAZO_API_KEY but not this one meant setting DS_DISABLE_PAID_BACKENDS=1 in .env
# had no effect on anything launched natively — the guard was silently inert exactly
# where someone would reach for it.
DS_DISABLE_PAID_BACKENDS
OCTOPRINT_API_KEY
DS_SCULPTOR_BACKEND
DS_SCULPTOR_REMOTE_URL
DS_SCULPTOR_REMOTE_KEY
DS_PIXAZO_GATEWAY
DS_PIXAZO_IMAGE_BASE_URL
DS_PIXAZO_UP_AXIS
TRELLIS2_PIPELINE_TYPE
PAUSE_ON_FAILURE
DS_NATIVE_ENV_KEYS
    unset _ds_key _ds_val
fi
