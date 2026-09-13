---
name: lit_search
description: "文献检索技能：学术多源检索、工具预算、禁止重复 query、Tavily 失败时切换学术源。触发场景：研究任务开始检索、需要补充文献、上传材料二次检索。"
version: 1.0.0
---

# 文献检索 Skill

把「怎么搜」写成可执行契约，而不是只靠系统提示嘱咐。

## 目标

在尽量短的时间内，收集 **≥6 条真实、可溯源** 的学术文献（标题 + URL/DOI/arXiv）。

## 工具优先级

1. `academic_fallback_search`（并行 Crossref + OpenAlex，失败再 EuropePMC/CORE）
2. `crossref_search` / `openalex_search`（精确加搜）
3. `arxiv_search`（预印本，有限流）
4. 网页源（tavily / ddg / wiki / searxng）仅弱兜底，失败一次就切换

## 预算（代码强制）

| 工具 | 每任务上限 |
|------|------------|
| academic_fallback_search | 2 |
| crossref_search | 2 |
| openalex_search | 2 |
| europepmc_search | 1 |
| core_search | 1 |
| arxiv_search | 4 |
| arxiv_download | 1 |
| tavily_search | 1 |

## 检索策略

- 先 2–3 条不同角度 query：`{主题} survey review`、`{主题} deep learning`、主题本身
- **禁止**重复发送相同 query
- 摘要通常足够；`arxiv_download` 最多 1 篇
- 出现 429 / 限流 / 冷却：停止该源，换源或用已有结果
- 用户上传文件已注入种子时：结合其主题与文末参考线索再搜一轮，**不要把上传摘录当成外部文献列入参考文献**

## 失败与质量

- 工具失败 → 进度里 `⚠️` 告警，结果不进文献池
- 真实文献过少（质量分过低）→ 任务 `failed`，不进入假审核
