# Commerce Copilot · 电商服务智能体

面向中小型自营商城的「导购 + 订单查询 + 售后预审 + 政策问答」自然语言服务层。
**PoC / 个人实战项目**，不是生产系统；所有指标均为离线评测或本地压测口径。

## 一、这个项目解决什么

| 痛点 | 解法 |
|---|---|
| 自然语言需求难映射到商品属性 | 结构化硬过滤 → BM25 + 向量双路召回 → RRF → 可解释精排 |
| 客服跨 4–5 个系统查一件事 | 工具网关统一封装 8 个业务工具，编排层按意图路由 |
| 退错、退两次、越权退 | 版本化规则引擎判资格 + 幂等键 + 订单版本乐观锁 + 归属校验 |
| 政策过期还照答 | 切块携带 version/effective_at/authority，回答强制引用，无证据拒答 |
| 模型被"忽略规则"诱导 | 身份服务端注入 + 工具白名单 + Pydantic 校验 + 规则裁决 |
| 效果说不清 | 离线评测集 + 固定脚本 + 可复跑报告 |

## 二、快速启动

```powershell
# 1. 激活虚拟环境（venv 在 D 盘，项目在 D 盘）
D:\venvs\commerce-copilot\Scripts\Activate.ps1

# 2. 填 LLM Key（可选，留空自动规则降级）
notepad .env      # 修改 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL

# 3. 启动（首次会建库、灌 2000 SKU 与 1000 订单、构建索引）
.\deploy\run.ps1
# 或
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 即为前端页面；接口文档在 http://127.0.0.1:8000/docs。

> 首次启动若使用 BGE-M3，会从 HF 镜像下载约 2.2GB 模型，之后走本地缓存。
> 加载失败会自动降级为哈希向量，并在 `/api/health` 的 `embedding_mode` 显示 `hash`。

## 三、目录结构

```
commerce-copilot/
├── app/
│   ├── main.py              FastAPI 入口（启动时建库/灌数据/建索引）
│   ├── config.py            配置（.env 优先）
│   ├── api/routes.py        chat(SSE) / confirm / orders / health / metrics / token
│   ├── core/                security(JWT+工具白名单) / cache(TTL+幂等)
│   ├── db/                  models / session / seed(2000 SKU, 1000 订单, 27 政策块)
│   ├── services/            product / order / after_sales_rules(规则引擎)
│   ├── retrieval/           embedder(BGE-M3→hash 降级) / index(BM25+向量+RRF) / rerank
│   ├── rag/                 policy_store / grounding(证据判断+引用) / chunker
│   ├── graph/               state / nodes(15 节点) / builder(状态图)
│   ├── tools/               contracts / contracts_schema(Pydantic) / gateway(网关+审计)
│   ├── llm/                 client(OpenAI 兼容) / prompts / rule_fallback
│   └── observability/       telemetry(trace/指标/审计落盘)
├── frontend/                index.html / style.css / app.js
├── eval/run_eval.py         离线评测脚本（写 eval/report.json）
├── tests/                   28 个测试：检索、规则、幂等、越权、注入、接口
├── docs/                    需求与架构设计 / 测试报告 / ADR
└── deploy/run.ps1
```

## 四、关键接口

| 接口 | 说明 |
|---|---|
| `GET /api/token?user_id=u0001&role=consumer` | Demo 签发 JWT（生产应接统一登录） |
| `POST /api/chat` (SSE) | `{message, thread_id}`；事件：status / token / result / done |
| `POST /api/confirm` | `{draft_id, idempotency_key, user_confirmed, expected_order_version}` |
| `GET /api/health` | LLM 模式、向量模式、索引规模、业务阈值 |
| `GET /api/metrics` | P50/P95/P99、错误率、token、工具调用数 |

## 五、安全设计（可被追问的部分）

1. **身份只从 JWT 注入**：`user_id` 不接受请求体传入；工具层与 SQL 层双重归属校验。
2. **越权与不存在同码**：统一返回 `ORDER_NOT_ACCESSIBLE`，避免订单号枚举。
3. **写操作四段式**：`prepare → user_confirm → idempotent_execute → audit`。
4. **幂等**：`draft_id + Idempotency-Key` 唯一约束，重复提交返回首次结果。
5. **版本冲突**：提交时校验订单 `version` 与规则 `rule_version`，变化即返回 `CONFLICT`。
6. **金额不由模型算**：退款金额恒来自规则引擎与订单实付；用户文本里的金额无效。
7. **检索内容视为不可信**：政策文本只作为证据，不能改变系统策略或工具白名单。
8. **无证据拒答**：RRF 分数与 BM25/向量命中低于阈值时不生成结论，转人工。

## 六、已知边界

- 数据为合成/脱敏；2,000 SKU、1,000 订单为 Demo 规模，生产容量只给计算方法。
- 不接真实支付；不自动审批退款；高风险（>1000 元）转主管。
- 多 Agent / A2A 未纳入核心：当前只有单 Orchestrator + 确定性子图，理由见 `docs/ADR-001-架构决策.md`。
- SSE 为应用层分块推送（非 LLM token 级流式），报告中的 TTFT 指首个文本块时间。

## 七、复现评测与压测

```powershell
python eval\run_eval.py                 # 写 eval/report.json：意图/检索/引用/延迟
python eval\load_test.py --concurrency 1 --requests 60     # 串行延迟
python eval\load_test.py --concurrency 20 --requests 160   # 并发压测
```

实测结果见 `docs/系统测试报告.md`：混合检索 MRR 1.0、政策引用 Top-1 100%、单请求 P95 266 ms、20 并发 P95 3.65 s（CPU 编码是瓶颈）。

## 八、测试

```powershell
python -m pytest tests -q
```

覆盖：硬约束不被语义相似度突破、越权拒绝、规则时限/品类例外、幂等只产生一条申请、版本冲突、未确认不执行、注入拦截、SSE 事件完整性。
