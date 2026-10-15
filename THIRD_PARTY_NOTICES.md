# Third-party provenance and attribution

This integration now includes the fixed upstream code/documentation snapshot in
upstream_reference/. It is no longer only a patch-only extension. The inventory
and precise exclusions are in UPSTREAM_MANIFEST.json and DATASETS.md.

Original project: YYHDBL/shopping-grpo-longhorizon and contributors.
https://github.com/YYHDBL/shopping-grpo-longhorizon/tree/449bba2686a6ff07327cb3ea77e5f0f91ebb4239

212 source/documentation/config/asset files are included. 211 are byte-identical;
README.md only has three remote badge token parameters removed. Original text,
credits and source provenance otherwise remain intact. Twelve data files are not
embedded. This is not a 224-file byte-exact repository mirror.

No root LICENSE/COPYING/NOTICE was found in the pinned upstream tree. The user
requested this public code integration after reporting permission from the author;
this does not establish or enlarge rights in embedded third-party code, images,
datasets, models or dependencies. No new license is chosen or claimed for those
materials or for the new extension. Public visibility is not a blanket license.

Embedded ShopSimulator identifies source commit
9ecba272963960ab4a10e1a781bd05cd7634ce20 and retains WebShop-related markers.
Templates reference Bootstrap, jQuery and a Bootsnipp snippet; five image assets
and dependency licenses are not independently cleared by this integration.
Adjacent upstream prose links a ShopSimulator paper, but that is not an explicit
per-image license statement. The audit describes the remaining scope precisely.

New code is separately located in prototype/, shopping_demo/, tests_demo/,
tests_integration/ and integration/verification scripts. Existing upstream action
guards, loop detection, context truncation, model training and evaluation are not
represented as original additions. The small text_parser_fix patch retains
limited original context and is attributed to the upstream source it modifies.

No product corpus, training/evaluation/example data records, raw simulator
observations, model weights, private experiment logs, environment directories,
account secrets or dependency binaries are included. Optional data can be fetched
explicitly to ignored local paths after the user establishes applicable rights.

See audit/PROVENANCE_AUDIT.md for source chains, unresolved permissions,
execution/telemetry/network risks and the exact token sanitation evidence.
