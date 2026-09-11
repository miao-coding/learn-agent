---
feature: p1-p2-citations-history-deps
status: delivered
updated: 2026-09-11
branch: main
commits: 9f6e0ed..83b231e
---

# P1 引用完整性 + P2 历史时间与依赖面板

## Report

**What was built** — 检索结果解析出真实 title/url/date 写入 references；撰稿结束后对正文 `[n]` 与文献列表对账，缺失编号补占位。历史 `updated_at` 由 UUIDv6 checkpoint_id 转为可读本地时间。侧边栏新增「依赖状态」面板，展示 LLM/Tavily/ArXiv 配置健康（可识别占位符 Key）。

**Verification** — `pytest tests/` **141 passed**；线上 `/api/research/history` 返回 `updated_at: "09-11 22:56"`；`/api/dependencies` 正确标记 `tavily_key_placeholder: true`。

**Journey log**
1. arXiv 结果里的 `arXiv ID` 可直接拼 abs URL；Tavily 用 `URL:` 行。
2. checkpoint 表无独立时间列，时间藏在 UUIDv6 前 60 bit。
3. 对账只补缺失编号占位，不重排 id，避免与正文编号错位。

## [S1] Problem

references 只有 query、无 URL；历史显示 UUID；无法一眼看出 Tavily 失效。

## [S2] Design

- `backend/utils/citations.py`：extract_reference_meta / reconcile_references
- `backend/utils/checkpoint_time.py`：uuid6_to_datetime / format_checkpoint_time
- `GET /api/dependencies` + 前端依赖 expander
- 历史列表 label 附带时间

## [S3] Out of Scope

- 全文强制重写以插入缺失引用；Tavily Key 注册

## Tasks

- [x] T1: references 元数据解析 — acceptance: arXiv 条目含 abs URL (covers: S2)
- [x] T2: 正文编号对账 — acceptance: 缺失 [n] 补占位 (covers: S2; depends: T1)
- [x] T3: 历史时间格式化 — acceptance: history.updated_at 为 MM-DD HH:MM (covers: S2)
- [x] T4: 依赖状态面板 — acceptance: /api/dependencies + 侧边栏展示 (covers: S2)
