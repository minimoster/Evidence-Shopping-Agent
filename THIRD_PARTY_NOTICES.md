# Provenance and public-content inventory

## Referenced upstream, not vendored

shopping-grpo-longhorizon by YYHDBL and its contributors:
https://github.com/YYHDBL/shopping-grpo-longhorizon

Pinned commit: 449bba2686a6ff07327cb3ea77e5f0f91ebb4239.
Embedded ShopSimulator provenance is recorded upstream in
environments/ShopSimulator/EMBEDDED_SOURCE.json, referencing source commit
9ecba272963960ab4a10e1a781bd05cd7634ce20.

No root LICENSE file was found in the inspected pinned source tree. This project
does not assert that the upstream code, data, models or training artifacts are
generally open-licensed. Obtain and retain the applicable permission yourself.
Public visibility of this extension does not expand any upstream permissions.

## Small retained references

- text_parser_fix/product_ids_text_parser.patch contains only the necessary
  local two-file modification and limited original context for applying the diff.
  Existing context remains attributable to upstream; do not treat it as wholly
  original code or as relicensed here.
- Minimal integration constants reference one public catalog product identifier,
  one short exact-title string, two visible color names and the selected prices
  1487/1492. These identify the reproducible boundary case, not a redistributable
  catalog. No raw product record, original task instruction, catalog dump or full
  observation is included.
- Test-module names and failure descriptions identify the upstream tests that
  were run. Runtime wrappers import the separately acquired upstream code.
- requirements-smoke.txt lists versions of third-party packages fetched from
  official PyPI; no dependency source or binary is bundled.

## Newly written extension files

prototype/*.py, prototype/tests/*.py, smoke/validation scripts, parser regression
tests, public documentation and compact report exports were prepared for this
independent extension. Existing upstream guard/loop/context/SFT/GRPO functions
are not represented as new contributions.

This repository does not choose or grant a new license for third-party content.
No license for the new extension has been selected yet; publishing source alone
is not an unrestricted licensing grant.

## Explicitly excluded

- The upstream checkout and complete original source modules.
- Product JSON/gzip archives, search indexes, training/evaluation datasets.
- Captured raw observations, original simulated task instructions, evidence ledgers.
- Model weights/checkpoints/adapters, virtual environments, caches and credentials.

All runtime outputs and the generated two-file overlay are ignored by Git.
