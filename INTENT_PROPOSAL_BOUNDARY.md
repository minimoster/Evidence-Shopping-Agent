# Intent proposal boundary: implemented, not NLU validated

The dev20 check at `880e05e` found both interfaces ready on **0/20** tasks.
Exact equality with a finite grammar protects against forged constraints but
does not parse unrestricted shopping language. This stage separates untrusted
proposals, structural/source checks and semantic acceptance. It adds no language
model or grammar expansion. See [cloud coverage](reports/dev20_880e05e_coverage.md).

## Three layers

`evaluation.intent_proposals` defines a query-only `ProposalProvider` protocol.
It is a future adapter contract, not a configured or callable model client.
Only `disabled` (default) and `offline_fixture` are implemented; the latter takes
an `OfflineProposal` inert data object. Callback/provider objects and real-model
mode are rejected before dispatch. No endpoint, credential parameter, retry loop,
network request or paid capability is introduced.

The proposal schema is independent of the bounded parser. It represents exact,
negative, alternative, quantity/interval, functional, compatibility and unknown
predicates with hard/soft/uncertain strength. Predicates reference exact original
Python Unicode spans. Ordered constraint/context/layout/unresolved segments cover
every character. Unknown units and functions can be represented without claiming
a proof procedure. A source reference does not prove that the assertion follows
from the referenced text.

`validate_proposal` checks exact keys, bounded plain JSON types, original-query
SHA256, character accounting, source equality, legal references and numeric/arity
contracts. It rejects malformed/nonfinite numbers and missing claimed units or
currency. It does not judge semantic entailment, completeness, compatibility,
semantic contradictions or whether text labeled context carries a requirement.

`inspect_intent` reports separate `source_check` and `semantic_acceptance` states:

| Semantic state | Meaning |
|---|---|
| `not_proposed` | Default; no proposal provider was invoked. |
| `rejected` | Schema/source checks failed. |
| `unverified` | Valid structure/source with no trusted semantic proof. |
| `needs_clarification` | Unverified proposal has unresolved/uncertain intent or lacks an explicit hard-ceiling claim; other unsupported intent can remain. |
| `rule_verified` | Exact agreement with the existing bounded-rule adapter, and that adapter is ready. Only its finite grammar is covered. |

`bounded_proposal` is an explicitly named legacy-rule bridge, not the natural-
language provider. Other valid proposals remain representable and unverified.
Confidence, matching spans or relabeling requirements as context cannot upgrade
them. No confirmation flag is accepted from a proposal. Every state, including
`rule_verified`, returns `purchase_authorized=false`: this is not an evidence
decision or a gate token.

## Budget classification without authorization

Proposals preserve `explicit_ceiling`, `approximate_target`, `soft_target`,
`nominal_target`, `range`, `absent`, `absent_or_unrecognized` or `ambiguous`, with
amounts, currency, comparator, approximation marker and source spans. A range's
upper endpoint is not silently selected as a ceiling. Approximate/missing/nominal
budgets receive no default or tolerance.

Reports distinguish **proposed** classification from **rule** diagnostics. The
latter reuses the limited analyzer and may say `absent_or_unrecognized`; it does
not establish that the user omitted a budget. A structurally valid ceiling can
still be semantically false. An approximate phrase with a fabricated hard-ceiling
proposal is an explicit negative test.

## Existing-flow integration

- `RunConfig.proposal_mode` defaults to `disabled`; `run_task` adds optional
  `proposal_fixture` while retaining old call signatures. Fixtures require explicit
  `offline_fixture` and `mocked_smoke`. Mismatches fail before the environment
  factory. Real execution cannot consume fixtures.
- `EvaluationEnvironment.reset` passes only the original public query, not task
  IDs, observations or private scoring fields. `run_task` records `intent_boundary`.
- A/B/C actor messages and purchase-gate arguments are unchanged. Untrusted
  proposals are not injected into model context or converted to QueryRequirements.
  C still calls original `verify_purchase` with canonical requirements and the
  current ledger.
- `summarize_query` adds the disabled-boundary diagnostic. Existing readiness
  booleans and clause counts keep their definitions; the bounded compiler and
  purchase-evidence rules were not changed in this stage.
- `real_cli.EVALUATION_EXECUTION_RELEASED` stays false. There is no real proposal
  transport to enable by passing another mode.

## Review and tests

One local author code review checked the source/semantics distinction, budget
classification, pre-environment mode checks, query-only inputs, additive output
compatibility and unchanged gate dispatch. This was not an independent review or
proof of NLU accuracy. Review tightened approximate-target shape consistency and
plain-string mode validation; unknown units deliberately remain representable
but cannot gain semantic approval.

19 original tests cover schema-valid hallucinations, context relabeling, span/
digest/reference tampering, numeric/budget errors, Unicode offsets, unknown intent
and units, absent provider dispatch, fixture modes, runner diagnostics and C-gate
preservation. They were not authored from dev20 instructions. Including original
parser/guard, experiment-manifest and mocked CLI regressions: **188 tests, zero
failures/errors/skips**, with socket/process audit events denied and no attempts.
[Machine-readable report](reports/intent_boundary_checks.json).

```powershell
python -X utf8 -m evaluation.semantic_checks --output results/intent-checks.json
```

Use a fresh output path. The suite uses inert mock provider/relay fixtures, never
real model requests. Cloud dev20 coverage is separately sourced and was not rerun
on Windows or against this later additive logging change. No NLU improvement,
semantic accuracy, product-evidence coverage or model success is claimed.

## Next concrete input

For an unpaid interpretation check, provide independently annotated original
queries, candidate proposals and human semantic judgments, including missing
budgets, negation, alternatives and unsupported requirements. Keep judgments
outside the purchase runtime. A future real proposing-model check additionally
needs a specified provider/model, authorized query transmission and finite call,
retry and cost limits before implementing/enabling its transport. Neither input
nor authorization is assumed here; no credentials or system changes are needed
to finish this engineering stage.
