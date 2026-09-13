---
feature: citation-truth-enforcement
status: delivered
updated: 2026-09-12
branch: main
commits: 1d481c0..9b8ff58
---

# 文献真实性强制（禁止编造）

## Report

**What was built** — 文献只能来自检索：多论文块按条拆分；禁止用 query 当标题；无标题且无 URL 的条目丢弃。撰稿后将真实文献重编号为 1..N、映射正文引用、删除编造编号，并整体重写参考文献章节。

**Verification** — `pytest tests/` **178 passed**；已部署服务器 `learn-agent-api`。

**Journey log**
1. 一次 ArXiv/Crossref 返回常含多篇，只抽第一篇会丢真实文献、助长「编号不够用→编造」。
2. 解析失败回退 query 当标题等于伪文献，必须禁止。
3. remap 时正则不要吞掉前导空白，否则 `[n]` 会被误删。

## [S1] Problem

用户要求：系统引用的文献必须真实，不能编造。此前虽删除了列表外 `[n]`，仍存在：

1. 一次学术检索常含多篇论文，只抽到第一篇，真实文献大量丢失  
2. 解析失败时用 **检索 query 当标题**，等于伪文献  
3. 无 URL/DOI 的可疑条目仍可进入列表  
4. 编号不连续时正文与列表对齐脆弱  

## [S2] Design

### 检索结果 → 多条真实 references

- `split_search_result_entries(text)`：按 `[i]` 条目切分  
- 逐条 `extract_reference_meta`  
- **收录门槛**：须有像论文标题（长度≥12 且不等于 query）或有 URL/DOI/arXiv ID  
- 过滤「未知来源」「未命名」「失败」等  

### 撰稿后强制对账

1. 过滤非法 references  
2. **重编号为 1..N**，正文 `[old]` → `[new]` 映射  
3. 删除映射后仍不存在的 `[n]`  
4. 用重编号后的真实列表整体重写「参考文献」章节  

### Writer 约束

- 仅可使用提供的 1..N；禁止发明标题/作者/年份  

## [S3] Out of Scope

- 逐句事实核验（claim verification）  
- DOI 在线 resolve 二次校验（网络不稳，可作后续）  

## Tasks

- [x] T1: 多条目切分与收录门槛 — acceptance: 4 篇 arxiv 块 → 4 条 refs；query 当标题被丢弃 (covers: S2)
- [x] T2: 重编号+正文映射+重写参考文献 — acceptance: 编造 [99] 删除；真实 refs 连续 1..N (covers: S2)
- [x] T3: 单元测试 + 部署 — acceptance: pytest 通过并上线 (covers: S2; depends: T1,T2)
