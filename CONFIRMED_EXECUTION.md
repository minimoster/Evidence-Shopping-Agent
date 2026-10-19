# Natural-language intake and confirmed simulator execution

This increment implements a callable, configurable model adapter and a complete
proposal/review/confirmation/decision/terminal-trace path. **It has only been
tested with offline transports and synthetic stores.** It is not evidence of
general NLU, a released autonomous shopper, or a successful real-model experiment.
The original dev20 canonical and bounded-parser readiness remains **0/20**;
the old 20-task / 60-run CLI remains disabled. No original query was recovered or
rewritten to improve that metric, and no paid model request was made this round.

## Run without network

```shell
python -m evaluation.confirmed_demo --output-dir results/confirmed-demo
python -m evaluation.semantic_checks --output results/confirmed-checks.json
```

Use a new output path each time: artifacts are exclusively created, never silently
overwritten or resumed. The demo's ordinary sentence, JSON interpretation,
confirmation and model actions are explicitly hand-authored offline fixtures.
It exercises the same adapter and runner contracts used by the opt-in real path.
A/B buy the synthetic white variant; C's first attempt is denied, its next action
selects black, and its third decision buys the now-matching variant. All three
finish. This is a recovery-contract example, not a model accuracy comparison.

The bounded suite has **213 passing tests, no failures/errors/skips**, including
25 new adapter, confirmation, accounting, failure and integration tests. The test
runner denies outbound sockets and process creation; zero denied-action attempts
were observed. [Recorded result](reports/confirmed_flow_checks.json).

## Implemented entrypoints

| Source | Responsibility |
| --- | --- |
| `evaluation/model_adapter.py` | Exact configured model/HTTPS endpoint, Chat Completions JSON/tool calls, bounded input/output/request exposure, no retries or redirects, sanitized errors and usage. |
| `evaluation/confirmed_intent.py` | Query-only model proposal, existing schema/source checks, review or clarification, digest-bound human confirmation. |
| `evaluation/confirmed_cli.py` | Offline preflight by default; interactive, newly authorized single-task execution against verified local simulator assets. |
| `evaluation/confirmed_runner.py` | Shared-confirmation ABC, fixed budgets, explicit missing/aborted rows, session accounting and separate score semantics. |
| `evaluation/runner.py` | Existing upstream collector/public-observation wrapper; confirmed protocol reuses the unchanged C evidence gate and recovery loop. |
| `evaluation/replay.py` | Offline confirmation/instruction binding and current-evidence gate consistency checks. |

### Proposal and human boundary

The model receives the original query and a schema description; no product catalog,
gold, persona, task annotations or simulator state is supplied to the proposal
request. Its output remains untrusted even with correct source spans. The same
`validate_proposal` contract checks the JSON shape and full Unicode source coverage;
it does not prove semantic entailment or detect every concealed/omitted constraint.

For executable v1 tasks, every proposed predicate must be a supported hard exact
field with no unit conversion. Unknown/unresolved, functional, compatibility,
negative, alternative, quantitative, uncertain and even soft predicates remain
visible and block execution; they are not silently discarded. The separate bounded
semantics research interface supports some richer predicates, but the old purchase
gate does not, so this execution path does not claim to support them.

The budget must be proposed as an explicit CNY ceiling, with a comparator and
non-approximate amount; the canonical compiler must accept the entire resulting
task. Approximate, nominal, absent, range or other-currency budgets stop for
clarification. The system never chooses a default ceiling or tolerance.

The CLI displays the **entire original query, proposal, candidate task and issues**.
Only a review with no blocking issues can receive explicit confirmation. The user
must attest that all hard requirements and the explicit ceiling are represented,
then type the review-specific digest phrase. Confirmation records bind the query,
proposal, candidate, statement and reviewer through canonical-JSON SHA256 digests.
This is a user-approved task interpretation, **not model correctness evidence**.
Human review can also be wrong. Checksums establish consistency, not authenticity:
the host must treat confirmation files/functions as trusted operator inputs, never
as model tools or untrusted remote payloads. The Actor has no confirmation tool.

Clarification stops the current run without actions; its review and billed/unknown
proposal attempt remain saved. There is no auto-fix, automatic re-proposal or hidden
budget reset. A revised query requires a new explicitly reviewed intake, and the
actual simulator reset query must still match the recorded original. This version
does not offer free-form multi-turn dialogue or silently edit simulator tasks.

### What executes and what is scored

All A/B/C arms receive identical original and confirmed task strings. B/C also
receive the existing structured-compilation intervention; C alone adds the existing
`prototype/purchase_guard.py` check. It reparses the **explicitly confirmed task**
and verifies current public ASIN, selected options, price, ledger revision and all
supported requirements. The original query remains in the trace and is independently
diagnosed. There is no proposal flag that bypasses the gate. A/B are experimental
no-evidence-gate controls, not safe real-world shopping policies. Real execution
accepts only the verified pinned `LocalSimulatorRuntime`, never marketplace adapters.

After rejection, the next model call sees current public feedback and may search,
inspect, change options or stop within its remaining budget. A denied buy consumes
one collector step and one decision call. Environment/model errors stop later arms;
uncertain dispatch is not marked executed, and no automatic retry occurs.

`original_task_success` retains the existing simulator's original-task gold score.
It is **not** a success label for a potentially changed confirmed task. The generic
`success`, `confirmed_task_success`, and confirmed success rate are null; independent
adjudication is unavailable. The old `evaluation.report.summarize` rejects confirmed
rows, preventing accidental mixing with original-query success or parser readiness.
The confirmed summary reports terminal states, purchases, original scores and usage.

### Equal budgets and accounting

One proposal is shared by all three arms. Each arm is charged its full proposal
call and token usage plus its own decisions under the same total call limit.
For an arm limit of N, at most N-1 decisions remain; the session must support
`1 + 3*(N-1)` physical requests before it starts. The physical ledger counts the
shared proposal only once, so summing logical per-arm usage is not a billing total.
The demo makes six offline transport attempts: one proposal, A=1, B=1, C=3 decisions;
logical counts including the proposal are 2, 2 and 4. These are not paid requests.

The exact model ID, endpoint, generation parameters, byte/token limits, task and
confirmation stay identical across arms. A fixed A/B/C order is used for this
single-task contract; counterbalancing/statistical evaluation remains future work.
Model ID equality only verifies what the response declares, not backend identity.

Every attempt reserves the operator-configured `per_request_reserve_usd` against
`max_reserved_usd` **before dispatch**. This is a conservative exposure ledger under
the operator's quote, not verified pricing, an invoice, or a provider-enforced
monetary ceiling. Missing billed cost remains null, never zero. The CLI requires
explicit acknowledgement of this limitation; use a provider-side budget before
authorizing real spending. Also enforced: finite attempt count, serialized request
bytes and requested output-token cap. `timeout_seconds` is a socket inactivity
timeout, not a strict overall wall-clock deadline. There are no model fallbacks,
discovery calls or automatic retries. All transport errors freeze the client.

`plan.json` is persisted before actions. `pending.json` is the original three-row
placeholder: recovery/reporting must overlay available `A.json`, `B.json`, `C.json`
on it, not count completed rows twice. Interruption can leave remaining placeholders.
Ordinary failures explicitly produce aborted rows for the remaining arms. Errors
contain types only; successful/failed transport usage remains in the physical
ledger even if later result processing fails. The CLI returns nonzero on execution
errors/aborted arms; normal step/call exhaustion remains a recorded terminal outcome.

## Optional real execution: not run or authorized by this change

The sample `configs/confirmed_model.example.json` contains no usable endpoint/key;
its monetary values are illustrative, **not a price quote**. Copy it to an ignored
local file and supply an explicitly selected endpoint, exact model and justified
finite limits. No credential is read from that file, environment variables or chat.
The only credential input is the user's no-echo prompt in a controlling terminal.

Preflight requires only that explicit config; it does not open the runtime, prompt
for a key, load private data or contact the network:

```shell
python -m evaluation.confirmed_cli --config configs/confirmed_model.example.json --runtime-dir runtime/shop --split-dir runtime/dev20 --task-id 302 --output-dir results/confirmed-one
```

Actual execution additionally requires `--execute-authorized` and
`--accept-quoted-reservation-risk`, valid operator-selected configuration, authorized
and verified local simulator/split assets, then the hidden key prompt and explicit
human review. **Do not run those flags without new authorization for model charges
and transmission of the query/public observations.** This new scope does not inherit
the historical no-monetary-cap `RealRunScope`. The API equivalent is
`prepare_intent` -> `confirm_intent` -> `run_confirmed_comparison`, reusing the same
client/session and an explicitly bound `ConfirmedComparisonScope` for real use.

Remaining validation: provider/API compatibility, independent intent completeness
and correctness labels, human-review errors, real public-evidence coverage and a
new independently adjudicated confirmed-task outcome protocol. The missing dev20
assets and failed Windows Library materialization were not retried or bypassed.

## Publication checks and contribution wording

`verify_publication.py` verifies HEAD (or `--index`) using canonical Git blobs,
independent of Windows CRLF checkout conversion. The new read-only GitHub Actions
workflow runs that verification, retained-upstream checks and the 213-test bounded
offline suite. Its fixed checkout action was resolved from the
[official v4 ref](https://api.github.com/repos/actions/checkout/git/ref/tags/v4).
No model, training, service stack, secret or complete dataset is used in CI.

An accurate resume description is: “Built a configurable LLM shopping-intent
adapter with digest-bound human confirmation, evidence-gated simulator recovery,
equal-budget ABC orchestration and auditable failure/cost traces; validated with
213 offline contract/regression tests.” Do not claim measured LLM accuracy,
improved real task success, completed RL training, or a production purchasing agent.
