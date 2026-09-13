---
name: analysis
description: "文献分析技能：从检索结果提取方法分类、性能对比、发展脉络、研究空白；输出结构化 JSON 并生成图表。触发场景：检索完成后进入分析阶段。"
version: 1.0.0
---

# 文献分析 Skill

## 目标

把检索到的真实文献整理成综述可用的**结构化分析**，并尽量生成对比图表。

## 必须产出的 JSON 字段

- `field_overview` — 领域概况与里程碑
- `method_categories` — 方法/技术路线分类
- `performance_comparison` — 性能对比（可含 Markdown 表）
- `timeline_analysis` — 发展脉络
- `research_groups` — 代表团队/机构
- `challenges_and_gaps` — 挑战与研究空白
- `key_findings` — 核心发现（≥3 条，尽量带引用编号）
- `data_sources` — 数据来源说明

## 规则

- 只依据检索到的文献与上传上下文，**禁止编造论文**
- 每个关键论断尽量关联真实引用编号
- 相互矛盾的结论要并列呈现
- 可调用 matplotlib 工具生成趋势/格局/对比图；图表按任务 thread 隔离
- 输出必须是 JSON（可从代码块中解析）

## 校验

缺字段会记入 `quality_metrics.analysis.issues`；严重缺失时撰稿质量分会下降。
