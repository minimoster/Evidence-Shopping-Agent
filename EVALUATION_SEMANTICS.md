# Bounded semantics and evidence review (2026-10-17)

This is an opt-in engineering interface, not general shopping NLU or a released
model experiment. It extends the earlier audit-only work with deterministic
semantic acceptance and predicate-specific public-evidence checks. The existing
canonical parser, A/B/C runner intervention and disabled real CLI remain frozen.
No development query was available in this clean checkout, so the new interface's
dev20 readiness is **unmeasured**, not 0/20 and not the synthetic test pass rate.
The historical canonical result remains 0/20 at main `e930882`.

## Implemented boundary

`evaluation.semantic_constraints` exposes four functions:

1. `propose_constraints(query)` takes only the original plain string. It returns
   a versioned JSON proposal, original-query SHA256, full clause/layout Unicode
   spans, typed nodes, hard/soft strength and unsupported/clarification reasons.
2. `validate_structure(query, proposal)` checks bounded plain-data types, exact
   keys, supported predicate/operator/unit contracts, numeric literals and source
   gaps/overlaps. This is not semantic acceptance. Even text falsely relabeled as
   layout can pass a structural check; the next check must reject it.
3. `accept_semantics(query, proposal)` independently derives the deterministic
   proposal from the original string and demands exact equality. Valid JSON,
   confidence, source coverage, a model's output or a second model's agreement
   cannot replace this rule. Outside-grammar text is never dropped.
4. `verify_constraints(accepted, ledger, intended_asin=..., intended_options=...)`
   repeats canonical acceptance and checks the latest ledger snapshot. It reports
   each predicate as `satisfied`, `violated` or `unknown`, with current evidence
   paths. Every unknown or violated hard predicate blocks approval. It performs
   no action. Re-run it immediately before any future action; its revision-bound
   report is not an execution token, lock, or proof that later state is unchanged.

The original `verify_purchase` only gained a shared snapshot-precondition helper;
its query reparse, grammar, budget and evidence contract are unchanged. Richer
constraints are not injected into its `QueryRequirements` or into the frozen
runner to make the existing treatment appear ready.

## Supported grammar and evidence

All examples below are original synthetic examples, not development instructions
or catalog excerpts. Clauses are joined by `;`, `；`, `,`, `，` or newline and form
a conjunction. No other prose is implicitly classified as harmless context.

| Predicate | Example | Required evidence / limits |
|---|---|---|
| Exact lexical value | `品类:水杯` or `颜色为蓝色` | Existing field vocabulary and exact case/whitespace-normalized atomic-value match; no substring, synonym, function or compatibility inference. The stricter atomic-value filter applies to colon values too; it does not change the older parser's separate literal-data convention. |
| Explicit alternatives | `颜色为蓝色或白色` | Two to four atomic literals retained in order; one current exact value must match. No choosing/dropping alternatives during parsing. |
| Selected-axis inequality | `颜色不是白色` | Positive, atomic current selected value on a complete color/size/package axis must differ lexically. No claim that a product lacks an ingredient, feature or component. An absent axis/claim is `unknown`. |
| Capacity comparison | `容量至少500mL`, `容量小于1L` | Current scalar selected capacity if it is an option axis; otherwise a current explicitly labeled capacity attribute. Operators: `至少`, `不低于`, `大于`, `至多`, `不超过`, `小于`, `为`. |
| Closed capacity interval | `容量在500mL到1L之间（含两端）` | Both endpoints and their units are explicit; inclusion is stated in the query. Reverse ranges block; unstated endpoint inclusion is unsupported. |
| Soft exact preference | `最好颜色为白色` | Retained and reported independently; never relaxes hard requirements. Conflicting hard/soft markers need clarification. Other soft predicate forms are not newly accepted. |
| Hard budget | `预算不超过80元`, `价格低于80元` | Exactly one explicit positive CNY product-price ceiling from the canonical grammar. Selected price must satisfy strict/inclusive comparator. No default, tolerance or fee-inclusive/order-total inference. |

Capacity units are only `mL`, `ml`, `毫升`, `L`, `升`; exactly 1 L = 1000 mL.
Decimal arithmetic uses a local precision independent of the application's
Decimal context. Quantity syntax permits up to 12 integer and 6 fraction digits;
budget syntax retains the original maximum of two fractional digits and is also
bounded to 12 integer digits at structural acceptance. No rounding, other unit
conversion, or inferred unit/currency is performed. Exact colon capacities need
a scalar with an explicit supported unit and remain exact lexical comparisons.

Multiple hard nodes for one field are conservatively blocked for clarification,
even if an intersection might be satisfiable. A single explicit interval avoids
that ambiguity. At least one hard category/title/model scope and exactly one hard
budget are required. Query length (4096), clause length (256) and whitespace-run
(8) limits apply before regex matching; rejected source remains intact.

## Unknown, unsupported, and clarification

- **Unsupported query:** free prose, function/compatibility/ingredient absence,
  nested logic, conditional purchases, unlabeled product intent, arbitrary units,
  multi-item quantities/totals and shipping/tax-inclusive totals. A future grammar
  or a separately confirmed explicit restatement is required, not silent repair.
- **Needs clarification:** absent, approximate, nominal or soft budgets; duplicate
  hard fields/budgets, conflicting strength markers, reversed intervals or
  unresolved alternatives. No automatic `±10%` budget policy exists.
- **Unknown evidence:** missing, malformed, conflicting or non-scalar claims;
  missing selected variant price; unselected axes; stale ASIN/variant/revision;
  unsupported evidence units; or a negative condition without a positive selected
  axis value. Unknown is never satisfaction. Literal inequality does not prove
  semantic absence (e.g. `不含白色`/`不含塑料` remain unsupported).

The verifier consumes only allowlisted current public snapshot facts. Generic
catalog attributes cannot override a selected axis. Product titles, old variants,
search summaries, hidden goal/reward fields, model assertions and original task
attributes do not fill gaps in the current candidate's evidence. The transport
that supplies public observations remains a trust boundary: fabricating a public
observation in application code cannot be detected as truth by schema alone.

## Existing development data adapter

`evaluation.semantic_readiness` reuses the existing verified dev20 selection and
pinned local simulator. It only resets and releases; it never steps, purchases,
calls a model or fetches data. Compilation receives only the original public
reset instruction. Reports retain all 20 slots, including failures/unattempted
slots after abort, and separate canonical readiness, new bounded readiness,
missing product evidence and unassessed task solvability. No query text is saved.

With already authorized local assets:

```powershell
python -X utf8 -m evaluation.semantic_readiness --runtime-dir runtime --split-dir runtime/dev20 --output results/semantic-readiness.json
```

This clean checkout has no `runtime/dev20/manifest.json`, `runtime/dev20/tasks.jsonl`,
`runtime/items_eval_train.json` or `runtime/products.sqlite3`. The adapter stopped
before runtime loading; zero real queries/steps/model calls were executed. See
`reports/semantic_readiness_status.json`. No replacement tasks or products were
fabricated. New grammar coverage and actual candidate proof require these inputs
and independent evidence review. The 60-run comparison remains disabled.

## Validation and reproducibility

```powershell
python -X utf8 -m evaluation.semantic_checks --output results/semantic-checks.json
```

152 selected tests passed, zero failures/errors/skips: 32 new tests plus 120
existing parser, guard and mocked runner regressions. The new cases are authored
independently of dev20 text, with literal expected outcomes; they are not blinded
third-party assessment. Coverage includes forged ASTs, source loss, alternative
tampering, numeric endpoints, approximate/missing budgets, contradictory fields,
unknown/variant-bound evidence and reset/release failure denominators. These are
synthetic rule and mocked integration tests, not model ability or real shopping
success. Socket/process audit events were denied; no attempt occurred.

The first combined run encountered the managed Windows default temporary-path
permission error in an existing trace-output test. The reproducible checker uses
this project's ignored `results/semantic-test-temp` instead; the complete selected
suite then passed. Python 3.14.6 was used; no dependencies were installed. The
Python launcher emitted a location warning for the preexisting Conda executable,
but all final checks completed with exit code 0.

## Relationship to upstream v2

The supplied upstream v2 review refers to
[`V2.0` commit 675131d](https://github.com/YYHDBL/shopping-grpo-longhorizon/tree/675131d3880d61d7a128b6b61aa1a56a7c079ac4).
This change adopts the separation of task solvability, intent coverage and
candidate purchase evidence. It does not copy training, teacher prompts, judge
assumptions, source code, or reported success rates; the bundled upstream source
stays pinned at `449bba2` and original attribution remains intact.

In particular, original task/gold attributes must not be combined with a different
purchased product's name/price/specifications as proof of that candidate. The
reported static risk in upstream teacher collection is a design caution, not a
locally reproduced labeling failure. Hidden labels, if used in a future independent
solvability audit, must stay outside purchase authorization. No training, new
credentials, model requests, real orders or author-performance reproduction was
performed in this stage.
