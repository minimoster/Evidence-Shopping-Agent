# Query-only rules and visible-evidence purchase guard

These are standard-library-only rule modules. They do not search, call a model,
execute a purchase, train a policy, or certify simulator task success.

## Clean-checkout tests

From this repository root:

    python -m unittest discover -s prototype/tests -v

The 65 synthetic unit tests need no package, model, key, upstream checkout or
catalog. Two optional integration test classes require separately acquired
upstream/captures and explicitly skip when absent. The historical complete local
workspace ran all 75 methods: 65 synthetic, three real public-builder/schema tests
with synthetic products, and seven captured-real-public-trace-related tests.
One trace case is an explicitly synthetic hidden-gold injection.

Raw captures are not published. Use the root README to acquire the fixed upstream
and regenerate results/public_simulator_trace.json locally, then rerun tests.
Only compact historical result exports are committed in reports/.

## Query-only requirements

    from prototype import parse_query
    requirements = parse_query("品类:耳机;预算:不超过100元;颜色:黑色")
    print(requirements.to_dict())

parse_query accepts only a query string, never annotations, task/goal objects,
observations or rewards. Accepted constraints and unsupported clauses retain
Python Unicode character spans into the original query. Any unsupported clause
blocks purchase approval rather than silently losing a requirement.

Supported grammar is deliberately narrow:

- Clauses separated by ;, ；, commas or newline.
- Explicit CNY maximum, e.g. 预算:不超过100元, 预算:低于100元 (strict), or 预算:100元以内.
- Explicit CNY/人民币/元/¥/￥ marker and at most two decimal places.
- Exact labelled category, title, brand, model, color, size, capacity, specification,
  package, material or attribute requirements. See FIELD_ALIASES in source.
- At least one category/title/model clause to establish product scope.

Not supported: general prose, omitted currency, bare 预算:100元, approximation,
ranges, k/万 scaling, alternatives, negatives, soft preferences, repeated axes or
unknown labels. Slash-containing values are conservatively ambiguous, so some
valid titles/category paths are falsely rejected. This is not broad NLU.

## Evidence ledger and gate

    from prototype import EvidenceLedger, parse_query, verify_purchase
    ledger = EvidenceLedger()
    ledger.ingest(public_state)
    requirements = parse_query(original_user_query)
    decision = verify_purchase(requirements, ledger,
        intended_asin=current_asin, intended_options=current_native_option_map)
    current = ledger.decision_is_current(decision, requirements)

Pass only the native observation_state dictionary, not the full reset/step info
or session/task/reward envelope. The gate never reads the product corpus or gold.

An approval requires:

1. Fully supported requirements; the gate reparses the original query to detect
   silently dropped compiled constraints.
2. The newest state is product_detail and its action list actually contains Buy Now.
3. Exact intended/current numeric-string ASIN (8–12 digits), preserving leading zeros.
4. Complete, unambiguous selected available-option axes and a matching intended variant.
5. Finite current price. Option-bearing products require explicit selected_price;
   no fallback to a cheap catalog summary. Explicitly optionless products may use
   an unambiguous scalar/singleton catalog price, never a minimum from a range.
6. Price within the explicit Decimal budget, respecting strict/inclusive bounds.
7. Exact current public evidence for every spec, using allowed fields/selected axes.
   Contradictory claims, missing proof, substrings and compatibility claims do not pass.

Evidence records source path, value, ASIN, variant and revision. Only the newest
snapshot is active proof. History is audit-only, not cross-page evidence fusion.
Every new observation invalidates an old decision, even if identical. ASIN/variant
changes never reuse prior prices, actions or specs. Malformed or hidden-key-tainted
observations replace the current snapshot with a rejecting state.

## Actual integration boundary

A separately executed fresh simulator produced five public states with no purchase:
reset, search, open a visible result, choose a visible variant, switch variant.
The gate ran synchronously on these states, not just cached replay. A hand-authored
exact-title/1490-CNY scenario yielded block, block, block, allow at 1487, block at
1492. The previous decision was no longer current after the switch.

This scenario was chosen to exercise a price boundary. It is not the original
environment task, an independent user need, a blind benchmark or a success rate.
The small integration constants in tests identify this reproducible case; no
full product record or raw observation is distributed.

After local preparation, the root README commands can regenerate the trace and
run the fresh gate with real_simulator_smoke.py --with-purchase-gate. Replay is:

    python -m prototype.replay_public_trace --output results/prototype_public_replay.json

These local outputs are ignored by Git and should not be force-added publicly.

## Limits

- High false rejection is intentional. Latest-snapshot-only proof cannot combine
  specifications seen on earlier pages, and free-text subpage content is not parsed.
- Native numeric simulator prices are assumed CNY; the schema has no currency field.
  Real merchant/foreign-currency use is unsupported without an explicit new contract.
- No shipping, tax, cart quantity, seller truthfulness, availability, refund terms,
  discounts or checkout totals are verified. This is not real-money authorization.
- Public metadata must come from a trusted environment. The gate cannot prove a
  merchant's claim or identify a wholly forged observation supplied by its caller.
- decision_is_current is a freshness helper, not a signed capability or transaction
  lock. Ingest fresh trusted state and reverify before any separately authorized action.
- No model, API, RL/SFT run, real purchase, task reward or held-out evaluation is
  represented by these results. Existing upstream features retain their attribution.
