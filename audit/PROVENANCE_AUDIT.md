# Source provenance and publication-hygiene audit

2026-10-15 UTC. Static review only, not legal clearance or a security certification.

## Scope and integrity

- [Upstream source](https://github.com/YYHDBL/shopping-grpo-longhorizon), fixed commit `449bba2686a6ff07327cb3ea77e5f0f91ebb4239`.
- `upstream_reference/` contains a selection of 212 source/docs/config/test/asset files (6,038,835 bytes) from 224 upstream blobs. This is not a complete training, dataset or model distribution. Generated caches are outside this selection.
- 211 files match their pinned Git blob hashes. Only `README.md` changed: exactly three opaque `sealed_token` parameters were removed from remote image URLs at original lines 407–409; all other bytes match upstream. Zero such parameters remain. No value is reproduced or capability tested.
- 207 text files were screened; five image blobs were hash-verified, not visually/metadata/rights-reviewed in this audit. See [source manifest](../UPSTREAM_MANIFEST.json) and [structured findings](provenance_audit.json).
- No upstream imports, installation, build, training, model/API call or remote write was executed by this audit.

## License and provenance observations

No LICENSE, COPYING, NOTICE, SPDX/copyright grant header, or project license field was found in the selected pinned tree. The publisher reports separately obtained upstream-author permission; this review did not inspect its text, ownership coverage or evidence. No LICENSE was added. Public hosting, citation or author permission is not treated as blanket clearance for independently owned material.

- Embedded ShopSimulator: `EMBEDDED_SOURCE.json` identifies [ShopAgent-Team/ShopSimulator](https://github.com/ShopAgent-Team/ShopSimulator), base `51bb26012cee31aea7ac26177c5ffe807026ac07`, source `9ecba272963960ab4a10e1a781bd05cd7634ce20`. Its runtime/tests/templates/static assets remain third-party material; product archive excluded. Separate rights/history were not independently verified.
- WebShop source markers remain. Search/done templates cite [a Bootsnipp snippet](https://bootsnipp.com/snippets/m13mN). Exact derivation and separate terms remain unverified.
- Templates load Bootstrap, Font Awesome and jQuery from external CDNs; their distributions, integrity and terms were not audited or vendored here.
- `uv.lock` records 273 packages: 271 PyPI, this editable project, and one fixed Transformers Git revision. It is not an offline dependency bundle or license inventory. The veRL-targeted patch retains respective source attribution.
- README/research references to ShopSimulator, veRL, Qwen, VitaBench, EComAgentBench, tutorial structure, TRACE/alphaXiv, DAPO and other work are preserved. They are provenance leads, not independent ownership/copying determinations.
- Five images lack independently verified image-specific permission in this audit. For `shopsimulator-overview.png`, README lines 29/46 (English 30/44) place a [ShopSimulator paper link](https://arxiv.org/pdf/2601.18225) near the image. Proximity does not prove the exact figure source or reproduction permission. The contributor evaluation image has context at `docs/evaluation-updates.md:7–41`. The static `no-image-available.png` also remains unverified.

## Sensitive-information screen

The opaque URL parameters above were removed and the exact limited transformation verified. No other confirmed live credential was found through targeted patterns for provider keys, private keys, credential URLs, secret/token parameters, assignments, email addresses and user home paths. `.env.example` has loopback endpoints and an `EMPTY` placeholder. Other reviewed key hits are environment/argument reads, documentation placeholders or mocked tests.

Pattern screening is not proof of absence. Binary image content/metadata, excluded data, Git history, credentials, runtime output and remote services were outside the text screen.

## Execution and network cautions

- `setup.sh` installs remote packages, expands excluded product data, builds an index and patches installed veRL. Do not run automatically in publication CI.
- SFT/GRPO/merge enable `trust_remote_code`; model loading/serving can download artifacts and consume GPUs. Model payloads, weights and terms are outside scope.
- Collection/evaluation and tokenizer helpers can send messages/text and bearer credentials to configured model endpoints. One helper defaults to `api.openai.com` without a base URL.
- SwanLab is opt-in, but enabled modes can use online telemetry; SFT's enabled-mode default is online.
- Explicit simulator/WebShop servers bind `0.0.0.0`; no authentication is shown in the inspected simulator API route. Use loopback or an isolated network before a separately authorized run.
- Rendering README/templates can contact remote badge/chart/avatar/CDN/product-image hosts; CDN JavaScript executes in a browser. This is not an offline-only reference.
- Some simulator imports configure log file handlers, so importing every module is not side-effect-free.

No symlink, gitlink/submodule, `.gitmodules`, `.gitattributes`, Git LFS pointer or GitHub workflow was found in the fixed inventory. Eighteen original files have executable Git mode. The build backend is `setuptools.build_meta`, with no tracked custom `setup.py`/build hook found. These checks do not certify dependency/model/runtime safety.

## Excluded and still unverified

The exact 12 omitted paths are in `provenance_audit.json`: eight JSONL, two parquet, the compressed product catalog and the duplicate report. Keep these, weights/checkpoints/adapters, raw observations/responses/logs, caches, environments, credentials and unreviewed Git history excluded unless separately reviewed and authorized.

Retained metadata/task-ID manifests, aggregate reports, examples, figures and citations remain upstream/derived material, not independently cleared assets. Historical performance summaries are not newly reproduced results or a complete verified training record. Preserve attribution, resolve third-party scope separately, do not imply blanket relicensing, and re-run publication checks after changes.
