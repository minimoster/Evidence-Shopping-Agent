# 离线端到端演示：非 LLM，不真实购物

新增可操作的需求确认页面 `/confirmed`：输入、人工预算澄清、确认、ABC 终态和只读回放。
见 [PRODUCT_FLOW.md](PRODUCT_FLOW.md)。它复用已确认任务运行器，明确使用有限手写
假模型；下面的旧首页与 CLI 仍为原脚本演示。

此目录中的 `shopping_demo/` 是原创增量，不是上游 Agent、模型或 ShopSimulator 的完整替代实现。它给现有 `prototype/` 购买证据闸门加上一个可运行、可单步、可回放的工具循环和本地界面。

**这里没有模型调用、API key、模型下载、训练或真实支付。** 默认商店是原创合成 fixture，商品名称、品牌、价格、属性与场景均为本项目手写，不包含抓取的真实商城数据。`success` 只意味着内存合成商店执行了购买动作，不是实际 ShopSimulator 成功、真实订单或评测成功率。

## 1. 克隆后直接运行

需要 Python 3.10+，本次使用 Python 3.12 验证。以下命令均在本项目根目录运行，即同时包含 `prototype/` 与 `shopping_demo/` 的目录。不需要安装第三方依赖；此演示不需要上游运行依赖，也不运行 `pip install`。

```bash
python -m shopping_demo serve --port 8765
```

在**运行命令的同一台电脑**用浏览器打开：

http://127.0.0.1:8765

只支持 `127.0.0.1`，不支持绑定 `0.0.0.0` 或把此服务暴露到公网。用 `localhost`、另一台电脑的 IP、反向代理或端口转发后的不同 Host 访问会被拒绝，这是有意的安全限制。按 Ctrl+C 停止。若端口已被占用，可改用 `--port 8766` 并打开对应地址。

界面明显标注“离线脚本演示 · 非 LLM · 不真实购物”，包含：

- 合成场景与窄语法 query 输入。
- 应用输入、单步、运行到结束、重置。
- 当前公开 observation、工具调用顺序、任务与轨迹 ID。
- 每次 buy 的真实 `prototype.verify_purchase` 结果、预算、变体与证据来源。
- 当前浏览器会话的公开事件回放、前后切换、回到当前与 JSON 下载。

修改输入后直接点“运行到结束”或“单步”，会先按新输入创建任务。点“重置”则重置当前已经应用的任务。回放不会重新执行工具。重置/新建任务后，之前的 trace 不再由该 HTTP session 提供；需要保留时请先下载 JSON。浏览器刷新保留当前 cookie 会话，服务进程重启后所有内存任务丢失。

## 2. 命令行与三类结果

```bash
# success：默认所选黑色合成耳机 79 元，预算 100 元。
python -m shopping_demo run --scenario success

# blocked：当前变体 129 元，超过默认 100 元预算。
python -m shopping_demo run --scenario budget

# blocked：当前变体价格未知，不使用 catalog 最低价代替。
python -m shopping_demo run --scenario unknown_price

# blocked：先观察到白色 69 元，切换黑色后没有当前价格，旧价失效。
python -m shopping_demo run --scenario variant_price

# failure：在第一个工具动作时，合成环境主动模拟不可用。
python -m shopping_demo run --scenario failure
```

这些场景不是使用隐藏答案决定正确行为：环境只提供公开商品状态，策略不知道场景名、隐藏目标或奖励。提高 budget 场景的显式预算会允许该合成商品，例如：

```bash
python -m shopping_demo run --scenario budget \
  --query '品类:耳机;预算:不超过150元;品牌:澄音;颜色:黑色'
```

`run` 总是把公共 JSON 轨迹写到 stdout，场景得到 `blocked` 或 `failure` 不是命令行程序崩溃，不使用非零退出码表示任务状态。无效命令、非法参数或不合法的 replay 文件才以非零退出。不要只用进程退出码判定任务成功，请检查轨迹的 `status`。

```bash
python -m shopping_demo run --scenario success > trace.json
python -m shopping_demo replay trace.json
```

`replay` 只读取你显式指定的本地 JSON 文件，检查公开观察与事件顺序，并重新调用真实 gate 比对记录中的 allowed/reasons。它不调用模型、不操作环境、不购买、不执行 JSON 中的代码。Web 服务**没有**读取任意文件或访问任意 URL 的接口。

轨迹不是签名日志，replay 不是来源真实性或防篡改认证；它只验证所记录公开证据与 gate 判定的一致性。它也不代表 Agent/RL 评测。不要把真实秘密写进 query，query 会按用户公开输入保存在轨迹中。

## 3. Query 语法

沿用 `prototype/requirements.py` 的显式字段规则，不是通用 NLU：

```text
品类:耳机;预算:不超过100元;品牌:澄音;颜色:黑色
```

必须有明确的人民币预算上限，以及品类/标题/型号之一。可用中文或英文分号、逗号或换行分隔。可识别字段与严格预算规则以 `prototype/README.md` 为准。自由描述、软偏好、缺失预算、歧义条件不会被默默丢弃来制造购买通过。当前合成目录只有一个原创耳机商品，泛化到其他商品不是此演示的能力。

## 4. 统一 Policy 与 adapter 接口

`shopping_demo.core.Policy` 是 `typing.Protocol`：

```python
def decide(self, query: str, observation: Mapping) -> ToolAction:
    ...
```

默认实现明确命名为 **ScriptedPolicy**，不是 LLM、不是训练过的 Agent，不支持智能问答。它从公开搜索结果选取满足显式品牌/标题/品类的候选，选择公开可用的精确变体，然后提出 buy。没有 `goal`、`gold`、`reward` 或 `info` 输入。它不会接收 task 对象、环境内部状态、隐藏目标、答案或奖励。

`ToolAction` 只接受严格参数的 `search/open/select/buy/finish`。每一个实际进入 runner 的 buy 在执行前都必须：

1. 再次读取当前公开 observation，白名单复制并拒绝非公开字段。
2. 使 `EvidenceLedger` 产生新 revision，不保留旧变体/旧页价格作为当前证据。
3. 调用原有 `prototype.verify_purchase`，传入由原始 query 编译的要求、当前 ledger、精确商品编号和所选变体。
4. 检查当前 decision 仍匹配 revision/query/商品/变体/价格。
5. 只有通过且 adapter 明确是本地 fixture，才执行内存 buy；任何未知、异常或不匹配都停止。

默认最多 12 个工具步骤，CLI/API 可选 1–50。达到上限、策略异常、环境异常、非法工具、非法/非公开 observation 均 fail closed。结束后的重复点击与重复 run 不会再次购买，同一 HTTP session 的任务操作串行化。

`ShopAdapter` 是单独的未来适配边界：

```python
fixture_mode: bool
def reset(self) -> Mapping: ...
def observe(self) -> Mapping: ...
def execute(self, action: ToolAction) -> Mapping: ...
```

**没有实现真实 ShopSimulator adapter。** 如要扩展，应单独实现 adapter，遵守相应上游许可，自行取得获授权的数据，并只映射公开 state；不要把 `(observation, reward, done, info)`、任务定义或内部字典整体传入。WebUI 不提供动态加载 adapter、模型、脚本或 URL 的入口。本 runner 禁止 `fixture_mode is not True` 的 adapter 执行 buy，不能拿它做真实购物。Python 接口不是针对恶意自定义代码的沙箱，标志位也不是安全认证；这些保证只针对本项目提供的实现。

真实商城还涉及并发价格变化、库存、运费、税费、支付、身份授权和真正事务锁，本离线 proof-of-concept 没有覆盖。公开 read 与 execute 分离不是跨外部系统的事务保证。不能把源码目录中存在训练脚本说成训练已经运行，也不能把这个合成工具循环当成训练、模型或真实 simulator 运行证据。

## 5. HTTP 安全边界

- 固定监听 `127.0.0.1`；精确检查 Host，若 Origin 存在必须匹配自己的 origin；拒绝跨站 Fetch Metadata。不设置 CORS 放行。
- 静态文件固定白名单，不由请求路径拼接文件系统路径；拒绝路径遍历、反斜杠、NUL、双重百分号编码、任意 URL。
- POST 仅接受 JSON、固定 Content-Length、最大 8192 字节，且要求 session 专属 CSRF token。
- 随机会话 cookie 使用 HttpOnly、SameSite=Strict；不把 cookie 值放入公共 state/trace。HTTP loopback 下故意不设置 Secure。
- task/trace 只在当前 cookie session 内查找，API 不接受目标 task ID 去访问别的 session。每个 session 只有当前任务，重置使旧 trace URL 失效。
- 最多 64 个内存 session，8 小时不活动清理，无账号、支付、持久存储、目录浏览、任意文件读取、外部 URL 抓取或动态执行接口。
- HTML/JS 用 textContent 输出动态内容；同源 CSP、禁止嵌入、nosniff；不记录请求内容、cookie 或 query。
- 白名单公开 observation；发现 goal/gold/reward/hidden/secret/token 等字段即拒绝；未知的其他字段不转发给策略或公共轨迹，异常文本也不进入轨迹。

这是本地研究演示，不是可部署的多用户产品或已经审计的安全网关。共享 cookie 的同一浏览器标签页共享 session，不是多账户隔离；要独立会话可用另一个独立浏览器配置文件或隐私窗口。不要公开部署或放入真实敏感信息。

## 6. 文件与验证

```text
shopping_demo/
  core.py           # Protocol、ScriptedPolicy、原创 SyntheticShop、Task、trace replay
  web.py            # ThreadingHTTPServer、固定路由、会话与访问限制
  __main__.py       # run / replay / serve CLI
  static/           # 本地 HTML/CSS/JS，无 CDN 或第三方脚本
tests_demo/
  test_core.py      # 离线工具循环、真实 gate、公开数据与失败边界
  test_web.py       # HTTP 安全、session 隔离、运行/单步/重置/并发重复请求
```

```bash
python -m unittest discover -s tests_demo -v
python -m unittest discover -s prototype/tests -v
```

2026-10-15 本次已实际执行 demo 单元/本地 HTTP 集成测试：**38 项通过**。覆盖统一 policy 签名、预算、未知价、切 variant 后旧价失效、buy 前的价格变化、每次 buy 真实 gate、步数上限、异常、非法工具、隐藏/秘密字段不入策略或公开轨迹、replay、localhost/Host/Origin/CSRF/body 大小/路径限制、跨 session task/trace ID 越权、重置与并发重复运行。五个 CLI 场景及各自的公开 JSON replay 均已实际运行，结果分别为 success / blocked / blocked / blocked / failure，replay 全部通过。`node --check shopping_demo/static/app.js` 通过语法检查。原有 prototype 测试输出为 `Ran 68 tests ... OK (skipped=1)`，其中可选捕获真实公开 trace 的测试因没有对应文件而跳过，不能宣称该项已验。

测试是合成 fixture 与 localhost HTTP 的功能证据，不是正式安全审计、真实商城测试、真实 ShopSimulator 评测、LLM 评测或 RL 训练结果。

**本环境尚未完成真实浏览器渲染/交互验收。** 集成阶段实际尝试云 Chrome 访问本地服务时得到 `ERR_CONNECTION_REFUSED`，直接 headless Chromium 也受沙箱 socket 权限限制；没有因此开放 `0.0.0.0` 或绕过访问限制。38 项 core/HTTP 测试通过和 JS 语法通过不等于浏览器渲染通过。请克隆到同一台本地电脑后，按第 1 节启动，并手动核验以下流程：

1. 默认成功场景连续单步，看 search → open → select → buy，核验 revision 与 79 元当前价格。
2. 切换预算、未知价、变体旧价失效场景，确认显示阻止且没有合成购买终态；failure 场景显示执行失败。
3. 调整窄语法 query 后运行、重复点击运行、重置、刷新页面；确认任务状态一致，不重复购买。
4. 点击工具时间线、拖动回放滑块、前后切换、回到当前，下载 JSON 后用 CLI replay 检查。
5. 用独立浏览器配置文件或隐私窗口建立另一 session，确认任务互不影响；缩窄窗口核验手机布局。
