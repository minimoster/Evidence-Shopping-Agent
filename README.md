# Evidence Shopping Guard

独立的购物需求结构化与可见证据购买核验原型，以及对既有 ShopSimulator
文本解析问题的最小修复。项目用于离线工程验证，不是已训练的购物 Agent。

上游项目：
https://github.com/YYHDBL/shopping-grpo-longhorizon

固定提交：449bba2686a6ff07327cb3ea77e5f0f91ebb4239

本仓库不搬运上游完整代码、商品库、原始商品 observation、训练数据或模型权重。
第三方归属与保留片段见 THIRD_PARTY_NOTICES.md。

## 个人增量

- prototype/requirements.py：仅从 query 提取显式预算/规格，保留原文跨度；
  窄语法无法解释的要求不会静默丢弃，而是阻止购买核验通过。
- prototype/purchase_guard.py：只接受公开 observation；每条证据绑定
  ASIN、variant、revision。未知价格/规格、超预算、选择不完整均封闭拦截；
  切换商品或变体后不复用旧价格或旧批准。
- text_parser_fix/product_ids_text_parser.patch：对固定上游两文件的小补丁，
  修复 SEP 文本产品提取与投影分派不一致，并增加注入/电话/价格误识别回归。
- 离线验证、完整语料哈希核对、真实 reset/step 接入和可复现报告。

上游已有的动作 guard、循环检测、历史截断、SFT/GRPO 不算本项目的新贡献。

## 已执行结果

- 原模拟器单元测试：43/43 通过。
- 固定上游选定契约测试：52 项中 48 通过、3 失败、1 错误。保留失败记录。
- 独立修复 overlay：同样 52/52 通过，另 44/44 安全/真实文本回归通过。
- 新原型：75/75 测试通过，其中 65 为合成单测，3 为真实公开 builder
  配合合成商品的 schema 测试，7 为真实公开轨迹相关测试。并非 75 个端到端任务。
- 完整 23,421 商品语料的哈希和 SQLite FTS5 索引已验证；语料不随仓库分发。
- fresh 真实环境执行 1 次 reset + 4 次 step，并同步调用新核验模块。
  手写集成场景的预算为 1490 元：当前规格 1487 元通过，切换至 1492 元后
  以 over_budget 拦截，旧决策失效。没有提交购买。
- 另有 3,000 个合成 JSON 状态与 2,000 个合成 query 的有界稳健性检查。

实际 Python 为 3.12.14，9 个逻辑 CPU；未安装 torch，未发现可用 NVIDIA 设备。
未调用模型或付费 API、未训练 SFT/GRPO、未下载权重、未执行完整任务集评测。
摘要见 reports/，实验细节与明确局限见 RUN_RESULTS.md。

## 先运行独立规则单测

只需 Python 标准库：

    python -m unittest discover -s prototype/tests -v

未获取上游、未生成真实 capture 时，相关可选集成测试会明确 skip。
公有仓库不附原始商品 capture，所以这一步不能重现本次全部 75 项集成测试。

API 与窄语法说明见 prototype/README.md。例子：

    from prototype import parse_query, EvidenceLedger, verify_purchase
    requirements = parse_query("品类:耳机;预算:不超过100元;颜色:黑色")
    ledger = EvidenceLedger()
    ledger.ingest(public_state)
    decision = verify_purchase(requirements, ledger, intended_asin=current_asin, intended_options=current_options)

public_state 必须是原生公开 observation_state，不是包含 goal/reward 的完整 info。
decision.allowed 仅代表这些窄约束的可见证据通过，不代表任务成功或交易授权。

## 按固定上游复现

先审查上游与脚本，并自行确认第三方代码/数据的使用权限。
不要运行原上游 scripts/setup.sh，它会安装超出本实验范围的 SFT/GRPO 栈。

    git clone --filter=blob:none --no-checkout --depth=1 https://github.com/YYHDBL/shopping-grpo-longhorizon.git upstream
    git -C upstream sparse-checkout init --no-cone
    printf '/*\n!/data/sft/\n!/data/sft_pure_v4/\n!/docs/images/\n!/uv.lock\n' > upstream/.git/info/sparse-checkout
    git -C upstream checkout --detach 449bba2686a6ff07327cb3ea77e5f0f91ebb4239

若浅克隆未包含该提交，需明确 fetch 固定提交后再 checkout，不要静默改用最新代码。

    python -m venv .venv
    .venv/bin/python -m pip install --index-url https://pypi.org/simple -r requirements-smoke.txt
    .venv/bin/python prepare_runtime.py
    .venv/bin/python offline_checks.py simulator
    .venv/bin/python offline_checks.py contracts
    .venv/bin/python offline_checks.py cpu
    .venv/bin/python real_simulator_smoke.py
    .venv/bin/python real_simulator_smoke.py --with-purchase-gate
    .venv/bin/python -m unittest discover -s prototype/tests -v
    .venv/bin/python robustness_checks.py
    .venv/bin/python validate_public_projection.py

contracts 在未经修复的固定提交上预期非零，不能把初始失败说成全绿。
准备及测试独立补丁的方法见 text_parser_fix/README.md。
实际执行环境与上述 fresh-venv 复现建议的差别见 RUN_RESULTS.md。

所有运行时数据、capture、索引、overlay、虚拟环境和日志均被 .gitignore 排除。
重新运行后不要强行添加这些文件到公有仓库。

## 不能据此声称

- 已实现通用 NLU、LLM 自主购物、跨页面智能规划或现实自动结账。
- 提高了多少购物成功率，复现了 GRPO 指标，或通过了原始任务。
- 手写边界场景是独立抽样/盲测任务，或把脚本动作回放算作模型决策。

当前证据只保留最新快照为有效依据，历史是审计而非跨页证据融合。
不核对现实结账的运费、税、数量、商家真实性、退款条款或实际币种。
正式 Agent 对照实验应单独明确模型、任务隔离、费用预算和指标。
