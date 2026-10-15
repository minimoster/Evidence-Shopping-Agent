# Optional data inventory

This is a complete upstream code/documentation integration, not a 224-file repository mirror.

Twelve dataset/catalog/example files are intentionally not embedded. Their redistribution permission scope was not independently established; this is not a finding that their use or redistribution is unlawful. Their combined size is 69,045,728 bytes. This selection was not a privacy finding, and no user personal data was identified by the exclusion rule.

All sources below are fixed at commit 449bba2686a6ff07327cb3ea77e5f0f91ebb4239. Hashes are Git blob SHA-1 (hash of the Git blob header plus file bytes), not plain-file SHA-1. The opt-in fetcher checks exact size and Git blob hash, then records SHA-256 locally.

| Path | Bytes | Git blob SHA-1 | Fixed source |
|---|---:|---|---|
| data/evaluation/tasks.jsonl | 3499 | 38b2e062d56ca61a5f589b4e37bf86edd8764e58 | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/evaluation/tasks.jsonl) |
| data/grpo/train.jsonl | 18538 | 9a1cc1d442b64fdc0a5e5b562e84c409ccdcd0da | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/grpo/train.jsonl) |
| data/grpo/train.parquet | 164108 | be861119c4c8b4b3ffdb72070bf28ad984183ab4 | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/grpo/train.parquet) |
| data/grpo/validation.jsonl | 925 | 53c12733d4ad5e7bb93c6d4a9c948cb2cf1c5eab | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/grpo/validation.jsonl) |
| data/grpo/validation.parquet | 24079 | 1d215f2a8d29a6214468771bea4a368bc6ee5c46 | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/grpo/validation.parquet) |
| data/sft/train.jsonl | 16858382 | 00dfece0d83ec460ee80d0442ac83b477e4d43f6 | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/sft/train.jsonl) |
| data/sft/validation.jsonl | 4105302 | c4da57f52dce51a5a4e162d7cc2d3bc47376c51c | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/sft/validation.jsonl) |
| data/sft_pure_v4/all.jsonl | 26779594 | 367e875c685deb2deaf07c30020c6561eaaa121b | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/sft_pure_v4/all.jsonl) |
| data/sft_pure_v4/difficulty_labels.jsonl | 490021 | 15f23c22d16daa1cacfeb901dbeda133000741ad | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/sft_pure_v4/difficulty_labels.jsonl) |
| data/sft_pure_v4/duplicate_report.json | 672481 | e9f9af4965a2a82abdc05848cd448ccaccaeab60 | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/data/sft_pure_v4/duplicate_report.json) |
| environments/ShopSimulator/shop_env/data/fine_items_eval_train_all.json.gz | 19923433 | 850e7d19558ebb609bbc184a7fa788e6b1075edd | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/environments/ShopSimulator/shop_env/data/fine_items_eval_train_all.json.gz) |
| examples/trajectories.jsonl | 5366 | b1f01de98fff1bb6f32f2f9bdeab8a2fda912716 | [source](https://github.com/YYHDBL/shopping-grpo-longhorizon/blob/449bba2686a6ff07327cb3ea77e5f0f91ebb4239/examples/trajectories.jsonl) |

## Explicit local retrieval

Default command only lists metadata and makes no network call:

    python fetch_optional_data.py

After you independently establish permission for the data you need, explicitly retrieve one file:

    python fetch_optional_data.py --select environments/ShopSimulator/shop_env/data/fine_items_eval_train_all.json.gz --allow-network --acknowledge-third-party-data

Or explicitly select all twelve files (about 69 MB):

    python fetch_optional_data.py --all-data --allow-network --acknowledge-third-party-data

Files are restored to their original paths under upstream_reference/. Existing files must match the pinned hash; unexpected files are not overwritten. There is no installation, model weight download, inference or training. All these optional data paths are ignored by Git. Do not force-add them to the public repository without separately resolving redistribution rights.

For the actual simulator after obtaining an authorized archive:

    python -m venv .venv
    .venv/bin/python -m pip install --index-url https://pypi.org/simple -r requirements-smoke.txt
    .venv/bin/python prepare_runtime.py
    .venv/bin/python real_simulator_smoke.py --with-purchase-gate

You may instead supply an already authorized local archive with prepare_runtime.py --products-archive /path/to/archive.gz. Its decompressed hash is checked against the pinned environment manifest.

Training additionally requires independently acquired compatible model weights, suitable compute, dependencies and any service credentials. Those are not included or claimed to have been run. Read upstream_reference/README.md for the original workflow. Do not execute scripts/setup.sh casually: it installs large stacks, prepares data and patches an installed dependency.
