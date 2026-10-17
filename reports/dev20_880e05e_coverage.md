# 原20题查询接口覆盖检查：云端执行记录

本记录转存自持有原始恢复包的云端任务提供的实际执行报告正文。
Windows 工程任务没有重跑这 20 条原文，没有取得完整原始 JSON；下述 JSON
SHA256 是云端提供的原报告身份，**不是此 Markdown 或重建 JSON 的哈希**。
Library 官方助手在 Windows 写入 xattrs 时失败，未绕过元数据使用临时文件。

固定提交：`880e05e16477248dd7581303582d387132959062`。
接口：`evaluation.semantic_readiness.summarize_query`；版本：`bounded-semantics-v1`。

20/20 题完成分析：完全支持 0、部分支持 3、需澄清 11、不支持 6。
新语义接口与原 canonical 接口的 ready 均为 **0/20**。
117 个子句：支持 3、需澄清 12、不支持 102。20 题均有不支持子句；18 题未识别出
接口认可的硬预算，19 题未识别出接口认可的硬商品范围。

四分类是报告层诊断映射，不是人类语义标签：ready 优先；否则有需澄清子句归需澄清；
其余有支持子句归部分支持；其余归不支持。需澄清任务也存在不支持子句，不能理解为
只补一个答案就能执行。B=未识别硬预算；P=未识别硬商品范围；U=超出有界语法；
C=不确定或未支持的约束语气。代码表示接口判断，不是人工认定用户原文缺少这些内容。

| task_id | 分类 | 原因 | 支持/需澄清/不支持子句 |
| --- | --- | --- | --- |
| 302 | 需澄清 | B P U C | 0/1/4 |
| 643 | 需澄清 | B P U C | 0/1/2 |
| 2511 | 需澄清 | B P U C | 0/1/5 |
| 2718 | 需澄清 | B P U C | 0/1/4 |
| 4199 | 需澄清 | B P U C | 0/1/4 |
| 12066 | 不支持 | B P U | 0/0/3 |
| 13399 | 需澄清 | B P U C | 0/1/10 |
| 14141 | 需澄清 | B P U C | 0/1/4 |
| 14929 | 不支持 | B P U | 0/0/3 |
| 15432 | 部分支持 | P U | 1/0/8 |
| 15586 | 需澄清 | B P U C | 0/1/5 |
| 16574 | 需澄清 | B P U C | 0/1/5 |
| 16715 | 不支持 | B P U | 0/0/5 |
| 17563 | 需澄清 | B P U C | 0/1/8 |
| 18176 | 不支持 | B P U | 0/0/5 |
| 18534 | 不支持 | B P U | 0/0/7 |
| 19090 | 部分支持 | B U | 1/0/2 |
| 20304 | 不支持 | B P U | 0/0/4 |
| 22823 | 部分支持 | P U | 1/0/8 |
| 23126 | 需澄清 | B P U C | 0/2/6 |

## 云端核验范围

- 原固定 20 题来自此前已核验 runtime 的公开 reset 指令；未 strip、删包装、改原句、
  补预算或根据商品/gold 补约束。分母未变。
- 输入 ZIP、文件 SHA256SUMS、20 条原始 UTF-8 指令哈希均通过；8 个导入源码文件
  与固定提交 Git blob 一致。
- 本次只执行纯标准库查询接口，未启动模拟器/商品服务，未调用模型、购买、修改解析
  规则或仓库。正文不含原查询。
- 这是原开发集接口就绪率，不是语义准确率、商品证据覆盖、购买成功率、真实模型
  评测或独立留出集。后续工程未据此修改原句、增加题号规则或删去失败题。

## 云端提供的可核查身份

| 对象 | SHA256 |
| --- | --- |
| 输入 ZIP | `7d3decda37ef148d85c3a2254ffd44848121ca0b7e257f6addf801adbe5561e7` |
| public_queries.jsonl | `3e7bdfc2841469ebe34215952bb4787bfbf631575071aa072e71e34e34d1e51c` |
| tasks.jsonl | `5b1dce23e1c1c7bc462da7bb931746facc57259156f848843c2939c0fb412990` |
| 完整原始 JSON 报告（未附于此） | `494a507a23f51587f099e06849ce0b2d8dd95fbdcd576d0dc9951b5c68acfcbe` |

| 固定源码 | Git blob |
| --- | --- |
| evaluation/__init__.py | `dd070da64c9c8ba344ef52746f44168434a89893` |
| evaluation/semantic_readiness.py | `b24465b4cd39aa3751228be5f5468ab782b0fa2b` |
| evaluation/semantic_constraints.py | `c422ad4422454f86c62ac6d3ea0d9fbfdda4a0d8` |
| evaluation/constraints.py | `05640a43f55dcbeb274cbca5a25cdabd041d29a6` |
| evaluation/query_analysis.py | `f721579b163109f28758daf7838dd830b72e7688` |
| prototype/__init__.py | `aa63a31285f26ba17aa59fcf5014b8521f17d524` |
| prototype/requirements.py | `8b1184025144474448f97985d0627d19994e60ee` |
| prototype/purchase_guard.py | `5cc789bbab8eb4b64322662dec228ed963c20ba2` |
