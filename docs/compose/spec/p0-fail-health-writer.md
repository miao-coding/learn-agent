---
feature: p0-fail-health-writer
status: delivered
updated: 2026-09-11
branch: main
commits: d3f9cf6..9f6e0ed
---

# P0：失败态、工具健康告警、撰稿输出校验

## Report

**What was built** — MAMBA 暴露的三类系统缺陷已闭环：检索/分析/撰稿失败进入终态 `failed`（不再伪装 reviewing）；Tavily/ArXiv 等工具失败会以 `⚠️` 实时推到前端并计入失败摘要；撰稿输出经 `_strip_llm_preamble` + `_validate_report`，脏输出最多重写一次。SSE 在 failed 时发 `phase:failed` + `error`，不再误报 completed。审核 API 对 failed 返回 400。前端支持 failed 历史图标、恢复与错误条。另修复 searcher 函数内 `import arxiv_search` 导致的 `UnboundLocalError`（任务启动即崩）。

**Verification** — `pytest tests/` **134 passed**；线上 MAMBA e2e（thread `49ccc229`，仅 ArXiv、Tavily 无效 Key）产出 reviewing 草稿约 **10234 字 / 18 引用 / 2 图**，以 `#` 开头、无前缀、单一 H1；Tavily 失败日志可见。已部署服务器。

**Journey log**
1. 线性图拓扑下 failed 需节点短路透传，否则会“走完”reviewer 把 phase 写回 reviewing。
2. `NODE_PHASE_MAP` 驱动的 SSE 阶段会掩盖节点真实 `current_phase`，必须优先读 state。
3. ArXiv 空结果文案是「未找到相关学术论文」，与 Tavily「未找到相关搜索结果」不同，漏标会重新引入假成功。
4. 函数内重复 `from ... import arxiv_search` 会形成局部绑定 → `UnboundLocalError`，即使顶层已导入。
5. 无有效 Tavily Key 时全流程可依赖 ArXiv 完成，但检索耗时显著变长（PDF 超时）。

## [S1] Problem

MAMBA 任务：搜索为空仍进审核、Tavily 失效无告警、撰稿前缀/重贴/乱码。

## [S2] Design

### 失败态（failed）

- 节点短路：searcher 无有效文献 / analyst 空或 LLM 失败 / writer 分析错误 → `current_phase="failed"`。
- reviewer/should_continue_or_end 对 failed 直接 END。
- SSE：`_finalize_stream` 与 `_handle_update_event` 对 failed 发 `phase:failed`（+ error），禁止 completed。
- 审核 API：failed → 400。

### 工具健康

- `_is_tool_failure` + `_TOOL_FAIL_MARKERS`（含「未找到相关学术论文」）。
- 失败结果不进文献池；`report_progress` 推送 `⚠️`。

### 撰稿校验

- `_strip_llm_preamble` + `_validate_report` + 一次纠错重写；仍脏则保留清洗结果。

## [S3] Out of Scope

- 引用完整性对账（P1）、多模型路由、Tavily Key 注册、全面条件边拓扑。

## Tasks

- [x] T1: searcher/analyst/writer/reviewer 失败短路 + supervisor END — acceptance: 空搜索 `failed`，不再 reviewing (covers: S2)
- [x] T2: searcher 工具失败 report_progress 告警 — acceptance: SSE 出现 `⚠️` (covers: S2; depends: T1)
- [x] T3: writer `_validate_report` + 一次重写 — acceptance: 脏输出可截断/重试 (covers: S2)
- [x] T4: 前端 failed 展示 + 审核 API 拒绝 failed — acceptance: failed 无审核框；POST review 400 (covers: S2; depends: T1)
- [x] T5: 单元测试 — acceptance: pytest 133 passed (covers: S2; depends: T1,T3)
