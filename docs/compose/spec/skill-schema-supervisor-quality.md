---
feature: skill-schema-supervisor-quality
status: designed
updated: 2026-09-12
branch: main
commits: 
---

# 技能层 / 结构化产出 / Supervisor / 质量门禁

## Report

## [S1] Problem

Agent 能力主要写在 System Prompt 里：检索顺序、分析维度、报告结构靠「嘱咐」，模型可漂。需要把策略收成可测的 Skill + Schema，并用 Supervisor/质量分做硬门禁。

## [S2] Design

### 1. Skill 包（`backend/skills/`）

- `SkillSpec`：name、description、tool_names、policy（预算/顺序/最少结果）、  
- `LIT_SEARCH`：工具优先级 academic_fallback → arxiv；arxiv 预算、最少真实文献数  
- `ANALYSIS`：必填 JSON 字段与校验  
- `REPORT`：必含章节列表与校验  
- 供 Agent 读取 policy，而不是只靠散文 prompt  

### 2. 结构化产出

- 分析师：沿用 JSON，增加 `validate_analysis_payload()`  
- 撰稿：`validate_report_structure()`（章节、引用、长度）  
- 校验失败 → 有限次重写；仍失败记入质量分  

### 3. Supervisor 质量门禁

在检索结束后、撰稿结束后打分（`quality_score_report` / `quality_score_search`）：  

- 真实文献数 < 阈值 → failed 或强制补搜一次  
- 报告缺章节/引用过少 → 重写或 failed  

### 4. 质量分（`backend/utils/quality.py`）

维度：references_count、citation_coverage、sections、length、fabrication_risk  
输出 dict，可写入 state / 日志 / 前端进度  

## [S3] Out of Scope

- 多模型路由、线上 A/B  
- 完整 claim-level 事实核验  

## Tasks

- [ ] T1: skills 包 + 校验函数 — acceptance: 单测覆盖 LIT/ANALYSIS/REPORT 校验 (covers: S2)
- [ ] T2: searcher/analyst/writer 接入 skill policy 与 schema — acceptance: 代码读 skill 而非仅 prompt (covers: S2; depends: T1)
- [ ] T3: quality 评分 + 门禁 — acceptance: 文献过少可 failed；报告结构分可计算 (covers: S2; depends: T1)
- [ ] T4: 测试与部署 — acceptance: pytest 全绿并上线 (covers: S2; depends: T2,T3)
