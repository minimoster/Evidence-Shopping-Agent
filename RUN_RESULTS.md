# Actual validation scope

Date: 2026-10-15. Source pinned to
449bba2686a6ff07327cb3ea77e5f0f91ebb4239.
No upstream tracked files or remote repository state were changed by the smoke work.

## Existing tests, before the separate fix

- Simulator: 43 run, 43 pass, no fail/error/skip.
- Selected contracts: 52 run, 48 pass, 3 fail, 1 error, no skip.
- CPU synthetic contract smoke: five checks pass, not five shopping episodes.

Four existing non-passing methods in test_observation_projection.py:

- test_search_projection_preserves_every_current_page_product
- test_guard_accepts_last_product_instead_of_creating_blind_spot
- test_second_environment_page_preserves_products_21_through_40
- test_capacity_mismatch_fails_instead_of_silently_dropping_products

Cause: the old SEP-text fixtures do not contain rank|ASIN table rows, while
product_ids only extracted table rows. Empty extracted IDs misclassified these
pages for generic truncation. Canonical structured v2 projection tests passed.

## Separate local patch

The original snapshot remains untouched. The overlay loads two patched modules
from an explicitly checked path; its runner records source hashes and exact
commit and denies network/process-spawn audit events.

- Same existing contracts: 52 run, 52 pass.
- Additional parsing/security/real-capture regression: 44 run, 44 pass, no skip
  in the complete local experiment workspace. Missing optional raw capture in
  a fresh public checkout is explicitly skipped until locally regenerated.
- The patch requires complete legacy ID/title/price triplets and a terminal
  action footer with matching unique IDs. Phone numbers, prices, extra IDs,
  ambiguous SEP content and mismatched footer data cannot add product targets.
- Canonical v2 handling is unchanged except safer first-line format dispatch
  and a cross-page-type product-ID preservation invariant.

## New rule prototype

- 75/75 unittest: 65 synthetic cases, three actual public-builder schema cases
  with synthetic products, seven captured-real-public-trace-related cases.
  One trace case is an explicitly synthetic gold-key injection.
- 3,000 synthetic JSON inputs, each verified twice for deterministic output;
  2,000 synthetic queries checked for exact source spans. Zero uncaught
  exceptions, determinism mismatches or source-span mismatches in this bounded run.
- These counts do not measure generalization, shopping episodes or success rates.

## Actual simulator and live gate

- Complete corpus: 23,421 products. Decompressed SHA-256 matches the pinned
  manifest: 57b10950a0064d16c81535a1d764a75879a508d250dde8a2a1787c5e6045559f.
- Standard-library SQLite/FTS5 index built over all products.
- In-process WebAgentTextEnv: reset once; search, open first visible result,
  select one visible option, switch to another visible option. Four step calls.
- No hidden target, task annotations, reward or gold fields drove these choices.
- New gate ran synchronously on five fresh public states, not only cached replay.
  A hand-authored exact-title/1490-CNY test scenario yields block, block, block,
  allow at 1487, then block at 1492. The old variant decision is invalidated.
- This query was selected for a price-boundary integration test. It is not the
  original environment task or a held-out benchmark; no task completion is claimed.
- Canonical public-state projection preserves all 20 search-product IDs and
  action footer entries: 2663 to 1524 characters. Patched real SEP-text projection
  preserves all 20 IDs/22 buttons: 2045 to 1520 characters. len is a deterministic
  character-count proxy, not a model tokenizer. An impossible budget fails closed.

## Environment and execution boundaries

- Python 3.12.14, nine logical CPUs; SQLite 3.53.1 with FTS5.
- No torch, no visible NVIDIA devices, no nvidia-smi; GPU execution not tested.
- No model inference, API key, paid API, downloaded weight, SFT/GRPO training,
  real purchase, HTTP service exposure or full evaluation-task run.
- Source/bootstrap packages were downloaded from public GitHub/official PyPI.
  Runtime verification scripts deny Python socket and process-spawn audit events;
  this is an audit guard, not a complete OS network sandbox.
- Working venv used --system-site-packages. Its NumPy 1.26.4 shadows global
  NumPy 2.3.5 only inside this venv. Unused preinstalled scientific/CAD packages
  produced dependency warnings; global packages were unchanged.
- A fresh non-inheriting venv download later encountered proxy 403 and was not
  used or retried. The README fresh-venv flow is a reproduction suggestion, not
  a claim that this second install succeeded in this environment.
- Upstream recommends Python 3.10 for the simulator; direct class construction
  worked on 3.12 here. gym.make and production deployment compatibility were not tested.
- Old Gym warnings and Flask/Werkzeug deprecations remain; no server was exposed.

Reports are compact exports of local results. Raw catalog-derived captures,
product evidence histories, environment directories and full logs are deliberately
not distributed by this public repository.
