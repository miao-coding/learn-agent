"""按主题粗选报告模板（指导撰稿侧重点，非硬切章节目录）"""

_REPORT_TEMPLATES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("survey", "review", "综述", "overview"),
        "survey",
        "全景综述：强调方法分类谱系、发展脉络、代表性工作对比表、研究空白",
    ),
    (
        ("change detection", "变化检测", "变化", "change"),
        "change_detection",
        "变化检测专题：任务定义（BCD/SCD/损害评估）、数据集与指标、方法家族对比、误差来源",
    ),
    (
        ("mamba", "ssm", "state space"),
        "ssm_mamba",
        "SSM/Mamba 专题：与 CNN/Transformer 复杂度对比、扫描顺序/双向建模、在遥感中的适配",
    ),
    (
        ("ch4", "methane", "甲烷", "no2", "pollution", "污染", "大气"),
        "atmospheric",
        "大气/温室气体专题：观测平台与传感器、反演/补全任务、物理约束与数据驱动融合、验证数据",
    ),
    (
        ("remote sensing", "遥感", "satellite", "卫星"),
        "remote_sensing",
        "遥感专题：影像模态、分辨率/重访、标注与基准、跨域泛化",
    ),
    (
        ("rag", "retrieval", "检索增强"),
        "rag",
        "RAG 专题：检索器-重排-生成链路、评估指标、幻觉与引用治理",
    ),
)


def pick_report_template(topic: str) -> tuple[str, str]:
    """根据主题关键词返回 (template_id, 写作侧重点说明)"""
    t = (topic or "").lower()
    for keys, tid, focus in _REPORT_TEMPLATES:
        if any(k in t for k in keys):
            return tid, focus
    return "general", "通用文献综述：背景—方法分类—对比—挑战—展望，引用必须来自真实文献"
