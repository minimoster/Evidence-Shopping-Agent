# Natural-language evaluation boundary and next interface

## Current status

The implemented compiler is `query-only-audit-v3-resource-bounded-not-general-NLU`. It is still a
bounded grammar, not a semantic shopping-intent parser. It adds natural **labeled**
clauses such as `商品名称是露光台灯，颜色为夜蓝，价格不超过73元。` to the original
colon grammar. That example is synthetic, not a task or catalog excerpt.

Natural clauses require a known explicit field label and exact lexical value.
Budgets require an explicit maximum, a positive Arabic decimal amount and CNY
currency. Natural sentence-ending `。` is grammar; punctuation in a colon-labeled
value remains literal. Unlabeled product prose, transport wrappers, numeric units
and ranges outside this grammar, conjunctions, negations, alternatives, preferences,
functional requirements, and extra text remain unsupported or ambiguous. They are
never dropped to obtain readiness. No approximate budget is turned into a maximum.
The lexical ambiguity filter is conservative, not a semantic-completeness proof.
The unchanged budget guard compares the selected product price only. It does not
prove a fee-inclusive transaction total, even when the accepted label is the
generic `预算`; explicit total-price, shipping-inclusive and multi-item-total
clauses remain unsupported. This is an existing simulator price-proof limitation,
not a guarantee of real-world total spending.

Linear checks before any clause regex reject queries over 4096 characters,
clauses over 256 characters, or whitespace runs over 8 characters. Rejected input
is retained in full and cannot become purchase-ready by truncation or rewriting.
These resource limits bound parsing work; they are not inferred user constraints.

The original query and Unicode source spans are retained. `compile_query(query)`
returns the exact `parse_query(query)` result. `verify_purchase` is unchanged and
independently reparses the original query, so replacing constraints or clearing
issues in a caller's object cannot authorize a purchase.

The local development-only reset report is
`results/natural_clause_dev20_validation.json`. It contains no raw query text.
Its counts describe grammar coverage, **not semantic correctness, safe-purchase
recall, task success or independent held-out evaluation**. The developer has seen
these development instructions; they are not a held-out test. Final200 instructions
and labels have not been inspected. No paid model calls or simulator purchase
steps are required for this reset-only check.

## Why a full comparison is blocked

1. Natural shopping intent is not generally an exact labeled value. Functions,
   compatibility, quantities, unit-bearing intervals, negation and alternatives
   need explicit predicate semantics, not a larger synonym or task-ID lookup.
2. Approximate, preferential or absent price statements cannot safely become a
   hard purchase ceiling. Choosing a tolerance or default would be a new policy.
3. The evidence guard currently proves only exact lexical facts from a current
   public observation. A correct richer parse would still not give it a proof
   procedure for functional, relational or quantitative requirements.
4. Complete character accounting only proves that text was not lost. It does not
   prove that each phrase was interpreted correctly. JSON/schema validation also
   cannot establish this semantic property.

Do not spend a 60-trajectory A/B/C comparison presenting an always-blocked C as a
meaningful evidence-verifier treatment. Report readiness and the blocker first.
Do not relax the guard, inspect gold, or substitute hand-labeled task-specific
constraints merely to produce nonzero C purchases.

## Proposed interface, not implemented or authorized to call a model

The next design should separate an untrusted proposal, semantic acceptance, and
public-evidence verification. The compiler's only task input is the original
public query string. It must not receive task IDs, product observations, catalog
rows, goal options, persona annotations, reward, task facts, or reference answers.
Model configuration/version may be pinned independently, but never changes the
per-task input boundary.

Proposed pure-data interfaces:

- `propose_constraints(query: str) -> ConstraintProposal`
- `validate_structure(query: str, proposal: ConstraintProposal) -> StructuralCheck`
- `accept_semantics(query: str, proposal: ConstraintProposal) -> AcceptedConstraints`
- `verify_constraints(accepted: AcceptedConstraints, snapshot: PublicSnapshot,
  intended_asin: str, intended_options: Mapping) -> VerificationResult`

`ConstraintProposal` should contain:

- Versioned schema, original-query digest, compiler identity, and a list of spans
  with original Python Unicode offsets and exact source text.
- Typed nodes: exact value, quantity with unit and comparator, interval with
  endpoint inclusion, negation, conjunction, and disjunction. A disjunction must
  retain all alternatives. Unsupported predicate types are not collapsed into
  a string or ignored.
- For every node, source spans, attribute/predicate type, literal value, and
  explicit hard/soft/uncertain status. Uncertain obligation strength blocks
  automatic acceptance; a guessed confidence score is not permission.
- Budget classification: explicit hard ceiling, soft target, range, absent or
  ambiguous. Preserve the currency, unit, comparator and approximate language.
  No default ceiling, currency, unit conversion, tolerance or rounding.
- `unsupported` and `ambiguous` spans with reasons, plus grammar/context spans.
  Every source character must be accounted for, with no constraint-bearing text
  labeled context solely to make the proposal complete.

`StructuralCheck` rejects unknown schema keys/types, invalid or mismatched spans,
non-finite numbers, illegal units/operators, dangling references, overlapping
inconsistent interpretations, dropped source text and contradictory constraints.
It does not return purchase authorization or certify semantic completeness.

`accept_semantics` is the unresolved trust boundary. A model-generated AST must
not replace the current deterministic reparse check just because its JSON is
valid or a second model agrees. Define an auditable acceptance procedure first,
such as a sound bounded semantic grammar and explicit user confirmation outside
that grammar. If a learned validator is used experimentally, label it probabilistic
and measure semantic errors separately; do not call it a deterministic guarantee.
Until this procedure exists, keep the current `verify_purchase` contract unchanged.

Each accepted predicate then needs its own evidence verifier. Exact facts can use
the existing ledger. Numeric and unit predicates need tested conversions, boundary
rules and current-variant evidence. Negation must not be proved by absence of a
claim. Functional/compatibility statements require an approved evidence rule; mere
title substring overlap, a model assertion, hidden scorer data or stale variants
are not proof. Unverifiable hard constraints return `unknown` and block purchase.
Soft constraints are retained for ranking/reporting, not silently promoted to
hard requirements or used to relax hard requirements.

## Decisions and evidence needed before implementation

- Agree on the supported predicate schema and the exact semantic acceptance
  boundary, including how unsupported but apparently irrelevant context is handled.
- Set an explicit evaluation policy for soft/approximate/absent budgets. Keep such
  tasks non-executable unless a separately authorized rule supplies a hard ceiling.
- Define proof procedures using only current public product/variant evidence.
- If a model is chosen, separately approve the query transmission, provider/model,
  compiler call budget, retries and pricing; include compiler cost in the experiment.
- Freeze the parser, policy and verifier before a new independent test. Use original
  synthetic adversarial tests for dropped clauses, negation, alternatives, units,
  approximate budgets, hallucinated fields, source tampering, prompt injection,
  forged ASTs, and stale evidence. Do not turn development task text into public
  fixtures or treat development tuning coverage as held-out semantic accuracy.
