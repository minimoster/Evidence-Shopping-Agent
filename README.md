# Evidence-Shopping-Agent

完整上游代码/文档整合，加上独立的需求结构化、可见证据核验和离线脚本演示。
**12 个数据文件未内嵌，这不是整个上游 224 文件的完整镜像，也不是已训练完成的 LLM/RL Agent。**

## 开发评测增量（2026-10-16）

新增 `evaluation/`：复用固定上游 rollout 和环境 adapter，提供 A 基线 / B
需求编译 / C 购买证据闸门的同预算接口、完整任务清单、失败分母、配对汇总、
重放与请求计量。拒绝购买后可以在原预算内修正，不重新赠送步骤。

可直接运行原创合成场景的脚本基线，无 API、网络、数据下载或 GPU：

    python -m evaluation.offline_baseline --output-dir results/offline-baseline

这是 scripted/mock 契约比较，不是 gpt-6.1-sol 或真实 ShopSimulator 的性能评测。
已准备的真实开发集是固定 20 题且与 Final-200 分离；数据与原始轨迹不再分发。
自然需求诊断保留原文位置、硬/软条件、歧义与未识别片段，不将诊断结果冒充
购买授权。安全闸门仍按原始 query 重新解析，复杂自由描述仍会保守拒绝。

真实 60 次任务-组实验尚未运行。完整执行入口保持关闭，等待需求语义/证据规则
完善及安全的人工密钥探测。仅支持指定模型 `gpt-6.1-sol`，不自动替换模型。
API 路径是待验证候选，token 数不等于已确认账单。详见
[评测状态](REAL_EVALUATION_STATUS.md)、[离线比较与失败分析](BASELINE_ANALYSIS.md)
及 [无回显探测](PROBE_README.md)。

## 内容与归属

- upstream_reference/：上游 shopping-grpo-longhorizon 固定提交的 212 个代码、
  文档、配置、训练/评测脚本、依赖锁及 5 个图片资源。
- prototype/：新增 query-only 窄语法规则、ASIN/variant/revision 绑定的购买证据核验。
- shopping_demo/：新增可运行标准库离线演示，使用显式 ScriptedPolicy 和原创合成商品。
- evaluation/：新增开发评测工程、查询诊断和明确标记的脚本基线。
- text_parser_fix/：新增最小修复 patch 与安全回归，原始源快照不应用该修复。
- UPSTREAM_MANIFEST.json：224 个原跟踪文件逐项映射、mode、大小、固定来源和 hash；
  212 保留、12 数据项排除。211 个保留文件字节不变，README 仅去掉 3 个
  能力未核实的远程图片 token 参数，修改已明确记录。
- DATASETS.md：12 项完整数据清单及显式按需获取方法。默认不下载、不安装、不训练。
- audit/：来源/许可未核项、敏感扫描和原脚本执行风险说明。
- reports/、RUN_RESULTS.md：实测范围与历史结果，失败和 skip 均保留。

原项目及贡献者：
https://github.com/YYHDBL/shopping-grpo-longhorizon

固定提交：449bba2686a6ff07327cb3ea77e5f0f91ebb4239。
上游已有 guard、循环检测、历史截断、SFT/GRPO 不作为我们的新贡献。
原代码/资料归属保留；图片、嵌入环境与依赖的第三方许可不能被推定扩大。
没有为原项目或新增部分擅自添加开源许可证，详见 THIRD_PARTY_NOTICES.md。

## 克隆后可直接运行：离线演示

Python 3.10+，仅标准库，不需模型、API key、GPU、原商品库或第三方包：

    python -m shopping_demo run --scenario success
    python -m shopping_demo run --scenario budget
    python -m shopping_demo run --scenario failure
    python -m shopping_demo serve --port 8765

浏览器打开 http://127.0.0.1:8765 。页面可以新建任务、单步、运行到结束、重置、
查看核验结果、浏览轨迹和下载公开 JSON。只绑定本地 127.0.0.1。
详细使用、五个合成场景与 replay 命令见 DEMO_README.md。

显著限制：ScriptedPolicy 是可替换接口下的规则脚本，不是 LLM。输入只接受
“品类:耳机;预算:不超过100元;品牌:澄音;颜色:黑色”这一类窄语法，非智能问答。
success 仅表示合成内存商店完成模拟购买，无真实账号、支付、订单或外部商城。
实际接口/HTTP 测试已执行；此环境浏览器访问 localhost 不通，浏览器交互未验证，
不能将 HTTP 测试声称为浏览器端到端测试通过。

## 无需下载数据的检查

    python verify_upstream_snapshot.py
    python offline_checks.py cpu
    python offline_checks.py simulator
    python -m unittest discover -s prototype/tests -v
    python -m unittest discover -s tests_demo -v
    python -m unittest discover -s tests_integration -v
    python text_parser_fix/prepare_overlay.py --upstream upstream_reference
    python text_parser_fix/run_checks.py --upstream upstream_reference --source overlay --suite all

原型真实 capture 测试、修复的真实 capture 测试会在缺少本地捕获时明确 skip。
上游原始 contracts 在原快照仍有 3 fail + 1 error；独立 overlay 修复后通过。
本项目没有为了全绿改写原始历史失败。

## 原始真实 ShopSimulator / 训练路径

原始完整代码在 upstream_reference/，原始说明位于 upstream_reference/README.md。
模拟器运行还需被排除的完整商品包；训练还需数据、权重、适合的计算资源和依赖。
请按 DATASETS.md 显式取得已授权数据后，再用 prepare_runtime.py 准备真实环境。
EVIDENCE_SHOPPING_UPSTREAM 可指向独立固定上游 checkout；不设时使用已内嵌源资料。

存在训练脚本不等于完成训练；上游文档中的成绩属于上游，不是我们本次结果。
没有包含未公开权重、私有日志、模型checkpoint、第三方完整商品库或账户凭据。
不要自动运行原 setup/训练脚本或把它们接入发布 CI。原环境服务会默认外网监听、
模型栈可能启用远程代码或遥测，执行前必须阅读 audit/PROVENANCE_AUDIT.md。

## 实际新增验证摘要

- 固定完整商品语料曾在受控本地工作区验证 23,421 商品及哈希，未再分发。
- 真实 reset 1 + step 4，并同步核验手写集成测试场景：1487 元可满足 1490 元上限，
  切换至 1492 元后拦截，旧决策失效。非原始任务/盲测成功率，无购买执行。
- 原模拟器 43/43；独立 patch 后既有 contracts 52/52，新增回归本地 44/44；
  公有 clean 环境不带真实 capture 时为 43 pass + 1 skip。
- 原型完整本地场景 75/75；整合版不带 capture 可跑 68 pass + 1 集成类 skip。
- 离线 demo 的 core/HTTP 测试和源码/数据工具测试见 reports/full_integration_checks.json。
- 无模型调用、付费 API、GPU训练、现实购物或新的完整任务集性能指标。

本次是“完整可读的上游代码资料 + 可运行离线工程增量”，不是“已补齐所有数据、
权重与实验日志，也已训练完成的完整智能购物系统”。
