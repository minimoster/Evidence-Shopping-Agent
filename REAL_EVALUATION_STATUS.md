# Relay preparation and actual validation status

The prepared configuration uses exact `gpt-6.1-sol` through
`https://st.walkcoding.top` for a finite 20-task A/B/C comparison. The full
execution entrypoint remains disabled. It is not unlimited iteration, training,
or real-world shopping. No authenticated model request has been made by this
implementation, and no backend identity has been verified.

## Minimal credential handoff

`relay_probe_standalone.py` is a standalone Python 3.10+ standard-library script.
The user can run `python3 relay_probe_standalone.py` in a real interactive terminal
on the computer/environment they selected, and paste the key only at the hidden
prompt. It does not save a key, accept key arguments/environment/files, or echo
stdin when secure input is unavailable. Never send the key through tool calls.

The default API path is an explicitly labeled candidate, not verified service
documentation. At most two requests are made: exact-model listing then a tiny
64-token connectivity request. No redirects, retries or alternative models.
Sanitized JSON records relay-declared IDs and any token counts; actual dollars
stay unknown. A 30-second socket inactivity timeout is not a strict overall
completion deadline. No simulator dataset is transmitted in this probe.

The standalone script was tested with inert offline fixtures, including missing
model/no-TTY handling. It has not been authenticated against the actual relay.
A successful relay ID is evidence of what the relay declares, not independent
proof of the backend model implementation.

## Actual pinned simulator checks (not mocked)

- Existing local CPU runtime loaded 23,421 products; no GPU or desktop/MMI used.
- Product SHA256: `57b10950a0064d16c81535a1d764a75879a508d250dde8a2a1787c5e6045559f`.
- SQLite SHA256: `630416ef3631aa1fc6ed50acd1ee12684d3bdd8888ab9d1e67bed6190b95b5e0`.
- Internal/external index manifests match. Selected dev IDs are pinned and disjoint
  from Final-200. All 20 public resets and releases passed.
- Actual runtime source matches the pinned upstream Git blobs/publication hashes.
  The older upstream environment metadata has one stale source-file hash;
  this discrepancy is recorded rather than hidden or used to alter upstream.
- Real simulator `step`/purchase/terminal rollout has not yet run.
- Offline CLI preflight was executed successfully: 20 tasks / 60 planned slots,
  zero credential requests and zero model requests.

## Why the 60-run comparison is paused

The original natural-language development instructions are ready for the initial
narrow parser in **0/20** cases. Many include ranges, conjunctions, soft preferences,
and approximate/absent rather than explicit upper-bound budgets. Treating these
as exact hard constraints would silently change intent. C would block every
purchase with the present contract. This is actual development parser coverage,
not a real-model score or full semantic assessment.

The paid 60-run experiment is paused pending a defensible
semantic compiler/verifier review. `real_cli` keeps full execution unreleased;
only the separate connectivity probe is ready for manual credential entry.
No Final-200 queries/answers were inspected or used for tuning.

## Prepared execution boundaries

`LocalSimulatorRuntime` reuses actual upstream `ShopAgentEnv` with an in-process
transport, upstream handler and slot pool. It binds only the exact 20 development
IDs and strips hidden reset fields/raw terminal HTML. No port/service is exposed.
The real runner requires this verified simulator, exact verified relay client and
explicit finite scope; ordinary smoke runs require injected fixtures.

The prepared relay transport refuses cross-host/HTTP URLs and redirects, checks
exact IDs, records every physical attempt, never auto-retries uncertain outcomes,
and stops the experiment on infrastructure/model errors. Proposed total budget:
1 discovery + 1 small smoke + 60 × 30 model calls = 1,802 physical attempts maximum,
30 steps/calls per task-arm. The two-hour admission window stops new requests,
not in-flight response time. Unknown billing is retained, not guessed from tokens.
Private response/error bodies and credentials are excluded from reports.

The experiment manifest keeps all 60 denominators, including errors and unattempted
slots after abort. Cleanup failures no longer prevent writing sanitized accounting
and reports. Use a local Python environment with the pinned simulator dependencies; the
standalone connectivity probe needs only the standard library.
