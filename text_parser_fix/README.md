# Strict text-observation product-ID parsing fix

This is a two-file correctness/security patch for upstream commit
`449bba2686a6ff07327cb3ea77e5f0f91ebb4239`. It does not add a compatibility
launcher, change the default environment/version, restore datasets or benchmarks,
call a model/API, or perform training/evaluation. The provided upstream checkout
is never modified.

## Public bundle contents

- `product_ids_text_parser.patch`: minimal Git diff for only
  `src/shopping_grpo/environment/actions.py` and `projection.py`.
- `prepare_overlay.py`: creates an ignored local two-file overlay from a
  user-obtained pinned checkout, after commit/source/patch hash verification.
- `run_checks.py`: independent offline test verifier. It validates the upstream
  commit/source hashes and loaded action/projection module paths and hashes.
- `tests/test_text_product_parsing.py`: 44 new test methods, including two
  deterministic 150-case subtest matrices and an optional real public-observation
  capture test.

Do not publish `overlay/`, `upstream/`, full logs, or raw observation captures.
No source repository, product archive, dataset, model or raw capture is bundled.
The overlay contains upstream-derived modules only after local preparation.

## Reproduce

Use an existing Python environment with the dependencies needed by upstream's
contract tests. No installation is performed by these scripts. Obtain upstream
separately and check it out at the exact commit above. For a normal Git checkout
at `/path/to/upstream`:

```sh
python prepare_overlay.py --upstream /path/to/upstream
python run_checks.py --upstream /path/to/upstream --source upstream --suite all
python run_checks.py --upstream /path/to/upstream --source overlay --suite all
```

The upstream baseline is expected to exit 1. The patched run exits 0 when its
checks pass. Locally these commands used the existing `venv/bin/python`; no
dependencies or default versions were changed. Preparation refuses an altered
patch, source mismatch, unexpected patch targets, symlink output, or a differing
existing overlay. It never uses `git apply --unsafe-paths`.

The verifier denies outbound socket operations and subprocess/OS command
execution during tests, disables new bytecode writes, and reports any denied
attempts. This is an offline contract subset, not a full repository suite,
200-task evaluation, training run, agent rollout or performance benchmark.
Its module-path overlay is a test-only loader, not an alternate application
entry point. Machine-readable summaries are written to ignored `results/`.

## Verified before/after

Existing contracts: before 52 tests, 48 passed, 3 failed, 1 errored; after
52 passed, 0 failed/errors/skips.

New regressions: before 44 tests, 29 passed and 15 test methods failed
(164 failure events including subtests); after 44 passed, 0 failed/errors/skips.
The local total is 96 passed. Failure-event counts are reported separately from
affected test-method counts.

The optional local capture was obtained independently from the actual simulator's
public legacy observation and its available-actions footer. It contains 20
visible products and 22 actions. Projection retained all 20 products and 22
actions while reducing 2045 characters to 1520 under a 1536-character budget.
The test looks for `../results/public_legacy_search.txt` relative to this bundle
and explicitly skips when absent. That raw file must not be published. Without
it, the portable expected patched result is 95 passed and 1 explicitly skipped
test out of 96, not 96 passed.

All token-budget checks here use `count_tokens=len`, a character-count proxy,
not a model tokenizer or evidence about a model's actual context usage.

Patch validation also passed `git apply --check`, application in a temporary
two-file source tree, byte equality with the tested overlay, syntax compilation,
and `git diff --check`. The fixed upstream working tree remained clean.

## Exact fix

`actions.py` keeps canonical first-line V2/PROJECTION `rank|asin|` recognition
unchanged. A SEP-bearing noncanonical observation instead uses one strict page
parser: Instruction, Back to Search, exact Page header, optional query/navigation,
then contiguous ASCII 8–12-digit ID/title/decimal-price-or-range triplets.
It requires one complete terminal Boolean/search + JSON action footer, unique
rows/buttons, matching navigation, and exact row/action product-ID equality.
It rejects malformed or ambiguous input rather than scanning forward or taking
IDs from descriptions, prices or the footer alone.

`projection.py` reuses that parser instead of scanning every numeric SEP segment.
Only a first-line canonical V2 marker selects the structured path, so a literal
marker in a legacy product title does not change dispatch. Its raw/visible
product-ID preservation invariant also applies to generic projection, preventing
truncation from turning embedded content into new actionable product rows.

Coverage includes phones, ID-shaped prices/titles, visible-but-nonactionable IDs,
footer-only/extra IDs, malformed/missing/duplicate footer data, duplicate IDs,
8–12-digit IDs and invalid lengths, SEP injection and malformed triplets,
newline rank-row injection, page navigation, real price ranges, final-product
guard behavior, full-page capacity, and canonical V2 literal-SEP behavior.

## Limits

- This intentionally recognizes only the frozen text template and tested public
  fixtures. Newline titles, literal SEP content, unexpected formats/whitespace,
  unknown actions and malformed pages fail closed rather than being guessed.
- The environment's terminal footer is the action authority. Grammar cannot
  establish provenance when a malicious party forges an entire observation and
  its footer together. Canonical structured rendering remains the preferred
  production contract and its original ID-recognition behavior is unchanged.
- Unmarked rank rows remain supported when no SEP is present. Unmarked rank rows
  with SEP intentionally no longer bypass strict text-page validation.
- No training, GPU, model/API use, dependency upgrade, production deployment or
  remote repository change was performed as part of this fix.
