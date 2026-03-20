# Autometa Rebrand — Infrastructure Phases

Phase 1 (done): renamed all user-facing strings, code identifiers, and
in-repo config from Matometa to Autometa.  Everything below involves
external side effects.


Phase 2 (done): Rename `gip-inclusion/Matometa` → `gip-inclusion/Autometa`.

---

## Phase 3: DNS and URLs

**Migrate domain names.**

- Update `BASE_URL` env var on all deployments
- Keep old domains as redirects for a transition period

## Phase 4: External Identities

- Email `matometa@inclusion.gouv.fr` — request from IT

## Signal Backward Compatibility

`lib/api_signals.py` currently accepts both `[AUTOMETA:API:...]` and
`[MATOMETA:API:...]` in its regex.  This covers the transition period
where old containers or cached agent sessions may still emit the old
prefix.  Remove the `MATOMETA` alternative once all deployments are
updated (after phase 4).
