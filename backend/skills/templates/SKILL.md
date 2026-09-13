---
name: templates
description: "按研究主题选择报告写作侧重点的模板库（survey/变化检测/Mamba/大气/遥感/RAG 等）。触发场景：撰稿前根据 topic 选模板。"
version: 1.0.0
---

# 报告主题模板 Skill

用 `pick_report_template(topic)` 得到 `(template_id, 写作侧重点)`，注入撰稿人消息，指导侧重而非替换章节结构。

## 模板一览

| ID | 命中关键词 | 写作侧重 |
|----|------------|----------|
| survey | survey, review, 综述, overview | 方法分类谱系、脉络、对比表、研究空白 |
| change_detection | change detection, 变化检测 | BCD/SCD/损害评估、数据集指标、方法家族 |
| ssm_mamba | mamba, ssm, state space | 与 CNN/Transformer 复杂度、扫描顺序 |
| atmospheric | ch4, methane, 甲烷, no2, 污染, 大气 | 观测平台、反演补全、物理约束融合 |
| remote_sensing | remote sensing, 遥感, satellite | 模态、分辨率、基准、跨域泛化 |
| rag | rag, retrieval, 检索增强 | 检索器-重排-生成、评估、引用治理 |
| general | （未命中） | 通用综述：背景—分类—对比—挑战—展望 |

实现见 `templates.py`：`pick_report_template(topic: str) -> tuple[str, str]`。
