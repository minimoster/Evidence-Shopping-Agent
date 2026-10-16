# Development evaluation preparation (2026-10-16)

This records the initial preparation milestone. Later relay preparation, actual
simulator validation, the manual no-echo probe and the current execution pause
are documented in `REAL_EVALUATION_STATUS.md`. No paid run has occurred.

**Engineering preparation, not a 20-task real-model report.** No model request,
GPU allocation, training, real-world order, or paid service was run. This historical preparation was based on GitHub main
verified as
`dcd16ea9de6510eeef2906ee5b38649786c7d6b5` on 2026-10-16.

## Reuse and provenance

`evaluation/runner.py` invokes the existing pinned
`shopping_grpo.evaluation.rollout.collect_for_task` and wraps its existing
`ShopAgentEnv`, renderer, normalizer and strict-success metric. It does not copy
or replace the rollout loop, train a model, or alter the upstream snapshot.
Attribution and licensing remain in `THIRD_PARTY_NOTICES.md` and
`UPSTREAM_MANIFEST.json`. The historical demo and its reported results remain
unchanged. The new code reuses the demo's recursive public-data taint check, not
its scripted policy or synthetic environment for real execution.

## Development split, not Final-200

`evaluation/dev_split.py` deterministically selects 20 IDs from the existing
50-task upstream GRPO validation pool. The source contains task IDs only; no
query, answer, training trajectory or Final-200 label was inspected. A separate
upstream IDs-only final exclusion manifest is required. Both input artifacts
are checked against the pinned upstream provenance, and source SHA256, Git blob
hash, exclusion hash, seed, selected IDs and output hash are recorded.

The prepared files are `runtime/dev20/tasks.jsonl` and
`runtime/dev20/manifest.json`, covered by the existing `runtime/` Git ignore.
They are local inputs, not public redistributions. A clean clone can use the
selector with separately obtained authorized inputs. Run
`python -m evaluation.dev_split --help` for the explicit source/provenance flags.
The selector refuses missing manifests, overlap, duplicates or insufficient
pools; it never fabricates substitute real tasks.

This is a development selection from prior validation data, not a fresh blinded
benchmark. No claim of training-independent generalization is warranted.

## A/B/C contract

- A: existing upstream actor prompt and legality guard, without compilation
  injection or evidence-gate enforcement.
- B: the same actor/collector plus query-only compilation in the model context;
  no additional purchase gate.
- C: B plus existing `verify_purchase` immediately before `click[Buy Now]`.

The compiler takes only the original reset user instruction, never a task
object, goal, TaskFacts or reward. The runner passes only task ID to the
collector, ignoring source task prompt fields. Hidden reset fields and private
terminal reward detail are stripped from actor messages. Public structured
states pass recursive taint checks before the renderer or ledger sees them.

Gate rejection supplies corrective reasons and the current public observation,
then allows another action within the original budget. It consumes one collector
step and one model call, does not execute the rejected buy, and does not reset
budgets. Upstream action-guard retries also consume the shared model-call budget.
Fresh environment leases and fixed split/config should be used for each arm.
The plan rotates arm order by task index to reduce time-order effects.

`configs/dev20-evaluation.json` records the proposed 20 × 3 experiment and limits.
`RunConfig` validates executable per-task settings. The config file is a
preparation plan, not a working paid-run command. `evaluation.experiment` now
provides manifest-bound deterministic offline orchestration with all task/arm
pairs, rotated A/B/C order and fresh injected clients/environments. `run_task` currently executes
only explicitly marked mocked-smoke clients; real mode is deliberately disabled.

## Parser audit and remaining NLU limitation

The original parser already has source spans but recognizes only explicit
clauses such as `品类:耳机;预算:不超过100元;颜色:黑色`. It is not a general natural-language
compiler. `verify_purchase` reparses the query and rejects altered compiled
requirements, so inserting externally inferred constraints would break the
safety invariant. The new compiler preserves the original canonical parse and
adds supported/unsupported/ambiguous span accounting instead of bypassing that
invariant. Unknown requirements are not silently accepted.

The compiler is therefore an auditable initial B interface, **not a solved
natural-language B system**. Natural user queries may be unsupported and C may
reject every purchase on those tasks. Real development-set parser coverage has
not yet been measured because the ID-only split has not been reset through the
real service. Any richer compiler must be query-only, retain source evidence,
represent negation/alternatives/soft constraints, validate ambiguity, and be
integrated with the guard's canonical validation before its results are trusted.

## Logging, replay and metrics

Each result has arm, execution kind, task/config, parser audit, public trajectory,
actual actor request contexts, model-call timings/usage, gate decisions and
revision-bound evidence. Private terminal payloads are used only in a temporary
scoring copy; they are not delivered to the actor or serialized as raw labels.
`write_trace` creates files exclusively and returns SHA256. Store generated
traces under ignored `results/`, never publish unreviewed data or secrets.

`python -m evaluation.replay results/trace.json` recalculates C gate decisions
from recorded public states without invoking models or the environment. This
checks consistency, not authenticity, and does not establish simulator success.

`evaluation.report.summarize` reports each arm separately, paired task outcomes,
all-task strict success, wrong purchases divided by all tasks and by purchases,
parser readiness, model calls, executed versus budget steps, latency, and tokens
and cost when actually supplied by the client. Missing usage is null, not zero.
Invalid/unadjudicated purchases make wrong-purchase rates unknown, not successful.
Use `summarize(rows, manifest=plan)` for experiment reporting. It verifies exact
experiment/config bindings and inserts explicit missing rows for every absent
expected pair, including a task omitted from all arms. These rows remain in the
success denominator; uncertain purchases/costs stay unknown. The report includes
expected counts, missing pairs and error counts. Without a manifest it explicitly
sets `manifest_checked=false` and is only a partial ad-hoc summary.

`ExperimentManifest` is persisted before rows when an output directory is given;
`from_dict` validates its canonical schedule on reload. `run_experiment` records
constructor/runner failures by type and continues, never silently dropping a
scheduled row. Interruptions propagate; the saved manifest allows incomplete
results to be reported honestly. Output directories are exclusive; automatic
resume/retries are not implemented. The development split loader verifies the
ID-only task bytes/hash and expected 20 IDs against the selector output. These
are consistency checks, not cryptographic proof of third-party provenance.

Strict success reuses upstream Reward-v3 complete valid gold-purchase semantics.
"Wrong purchase" is an explicit valid Reward-v3 `wrong_purchase` terminal label.
Valid/partial alternatives are not strict gold success, but are not mislabeled
as wrong purchases. Unknown/incomplete reward contracts remain unadjudicated. **Gate false-rejection rate
is null** until an independent post-run adjudicator evaluates valid candidate
attempts. Later task success is not a false-rejection label; labels must never
feed recovery actions. No made-up zero-percent error or parser-coverage claim.

## Offline verification

    python -m unittest discover -s tests_evaluation -v
    python -m unittest discover -s prototype/tests -v
    python -m unittest discover -s tests_demo -v
    python -m unittest discover -s tests_integration -v
    python verify_upstream_snapshot.py

New runner tests explicitly use `FakeClient` and `FakeEnvironment`. Split tests
use original synthetic ID fixtures. They are smoke/contract tests, not real LLM
or real simulator performance. Existing optional live-capture tests still skip
when their capture file is absent. Tests do not activate paid execution.

## Retry-inclusive spend interface (not a transport)

`evaluation.spend.SpendLedger` is a standalone, provider-independent serial
accounting contract. It accepts explicit Decimal USD bounds, reserves exposure
before each physical request, counts every retry separately, retains the full
reservation for uncertain responses and rejects unknown pricing. Verified final
costs can release unused exposure. An over-bound bill is recorded and freezes
future reservations. Unknown actual total cost remains null, never zero.

The ledger is in memory and not connected to a provider or runner. It does not
claim durable crash recovery, concurrency safety, real billing guarantees, or
control over arbitrary clients. A future integration must use one shared ledger
for the approved scope, disable unaccounted SDK retries, reserve before every
request, persist safely, and reconcile billed usage. These offline tests do not
authorize requests or unlock the real execution path.

## Historical prerequisites from initial preparation

The provider adapter and in-process simulator were subsequently implemented;
see `REAL_EVALUATION_STATUS.md` for current blockers. This original checklist
is retained for context, not a claim that those later interfaces are absent.

1. Choose an approved provider, exact model/version, endpoint, context/output
   budget, retry policy, and maximum total spend. Approve transmitting public
   task text and product observations to that provider. Do not paste credentials
   into repository files or chat; use the supported secure configuration route.
2. Implement and test a provider transport that captures billed usage and
   pricing, accounts for every retry, enforces total spend before requests,
   bounds wall time, and preserves unknown/uncertain costs. The upstream client
   does not currently expose usage and may retry; its call count alone is not a
   sufficient financial cap. Only then deliberately unlock the real execution
   path with explicit authorization. No GPU is required by this preparation.
3. Start the pinned ShopSimulator with authorized local product data and exact
   dataset hashes, on loopback only. Validate environment v2.1, observation v2,
   tool schema v2 and Reward v3. Confirm selected IDs resolve to the same pinned
   goal indexing. No desktop/MMI process is involved.
4. Connect the tested offline experiment orchestrator to the approved transport
   only after provider safeguards are tested. Manifest validation, all expected
   rows, fresh leases and rotated arms are implemented. Add authorized resume
   semantics and a shared spend ledger across every request/retry before enabling
   a paid run; configuration or labels alone cannot enforce network behavior.
5. Run the 20-task development comparison only, inspect replayable failures and
   unsupported-query coverage, then decide whether a richer compiler is needed.
   Keep Final-200 sealed. Add independent post-run candidate adjudication before
   reporting false rejections. No training or final benchmark is authorized.

Default smoke execution now refuses to create `ShopAgentEnv`: an explicit
fixture factory is required, and directly passing that network adapter is
rejected before any request. This prevents accidental default network use, but
arbitrary injected Python factories/clients remain trusted code, not a sandbox.
An `execution_kind` string is labeling, not proof of offline behavior.

This milestone prepares safe interfaces and tests; it does not claim the
remaining paid-provider orchestration or full NLU work is already complete.
