"""撰稿人 Agent - 将分析数据整合成结构化 Markdown 文献综述

撰稿人接收分析师的结构化数据，结合研究方向，
使用 LLM 撰写结构完整、引用规范的学术文献综述报告（Markdown 格式）。
支持根据审核反馈进行针对性修改。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.tools.rag import rag_search

logger = logging.getLogger(__name__)

# ── 撰稿人系统提示词 ─────────────────────────────────────────────
WRITER_SYSTEM_PROMPT = """你是一个专业的学术综述撰稿人。你的任务是根据分析师提供的数据，撰写一份结构完整、引用规范的文献综述报告（Markdown 格式）。

报告结构要求：

1. **摘要（Abstract）** — 200-300字，概括综述范围、主要方法脉络与核心结论
2. **引言（Introduction）** — 研究背景与意义、综述的范围界定、文献来源说明
3. **研究现状与分类（Taxonomy）** — 按方法/技术路线分类梳理现有工作，阐述各类原理与代表工作
4. **方法对比与分析（Comparison）** — 使用 Markdown 表格对比各方法的性能指标、优缺点，结合图表深入分析
5. **挑战与研究空白（Challenges & Gaps）** — 现有工作的局限性、尚未解决的问题
6. **总结与展望（Conclusion）** — 领域发展趋势、值得关注的未来方向
7. **参考文献（References）** — 所有引用来源的完整列表

引用格式要求：
- 正文中所有论断、数据、观点必须使用 [数字] 标注引用来源
- 引用编号与分析师提供的引用编号对应
- 报告末尾的参考文献列表按编号排列，包含文献标题和URL
- 严格依据提供的引用来源撰写，不得编造不存在的文献
- 示例：Transformer 架构自提出以来已成为该领域的主流方法 [1]。

写作要求：
- 学术综述风格，客观、严谨、以文献为依据
- 明确区分领域内的“共识”与“争议”，对矛盾结果并列呈现不同文献的观点
- 使用 Markdown 格式
- 报告长度 2500-5000 字
- 合理使用表格与图表（分析师生成的图表路径）展示对比数据
- 如果有修改意见，请针对性修改并确保质量提升

RAG 检索能力：你可以使用 rag_search 工具从向量数据库中检索相关文档片段。
当你需要核实某个论断的文献依据、补充引用细节时，主动调用 rag_search 获取最相关的信息。

输出硬性约束：
- 直接输出完整 Markdown 报告正文，必须以 `# ` 标题开头
- 禁止输出“已核实完毕/以下是报告/修正后重新输出”等过程说明
- 禁止把同一份报告重贴多遍；若需修改，只输出一份最终完整报告
- 禁止重复“参考文献”章节
- **引用必须真实**：只能使用下方「引用来源列表」中已有的编号 [1]..[N]
- **禁止编造**列表之外的编号，禁止发明不存在的论文标题/作者/年份
- 若某论断没有对应文献，宁可写“相关公开资料显示/概括性表述”，也不要编造 [n]
- 末尾「参考文献」只列出你实际用到的、且在提供列表中的编号
"""

# ── 分节撰稿：多次短调用拼装，降低长请求 524 ─────────────────────
_REPORT_SECTIONS: list[dict[str, Any]] = [
    {
        "key": "abstract",
        "heading": "## 摘要",
        "hint": "200-300字：范围、方法脉络、核心结论",
        "max_chars": 500,
    },
    {
        "key": "intro",
        "heading": "## 1. 引言",
        "hint": "背景与意义、综述范围、文献来源说明",
        "max_chars": 700,
    },
    {
        "key": "taxonomy",
        "heading": "## 2. 研究现状与方法分类",
        "hint": "按方法/技术路线分类，原理与代表工作；多用 [n] 引用",
        "max_chars": 1400,
    },
    {
        "key": "comparison",
        "heading": "## 3. 方法对比与分析",
        "hint": "Markdown 表格对比优缺点/复杂度/适用场景",
        "max_chars": 1000,
    },
    {
        "key": "challenges",
        "heading": "## 4. 挑战与研究空白",
        "hint": "局限与未解决问题",
        "max_chars": 700,
    },
    {
        "key": "conclusion",
        "heading": "## 5. 总结与展望",
        "hint": "趋势与未来方向",
        "max_chars": 500,
    },
]


def _split_previous_sections(previous_report: str) -> dict[str, str]:
    """把上一版报告按二级标题切块，宽松匹配到分节撰稿的章节 key

    标题匹配容忍编号/措辞差异（如「## 1. 引言」vs「## 引言」）；
    参考文献等未匹配块忽略（由引用对账统一重写，不进 LLM）。
    """
    import re

    if not previous_report or not previous_report.strip():
        return {}

    section_words = {
        "abstract": ("摘要", "abstract"),
        "intro": ("引言", "introduction", "背景", "background"),
        "taxonomy": ("现状", "分类", "taxonomy", "综述范围"),
        "comparison": ("对比", "比较", "comparison", "性能分析"),
        "challenges": ("挑战", "空白", "challenges", "局限"),
        "conclusion": ("总结", "展望", "conclusion", "结论"),
    }
    result: dict[str, str] = {}
    for block in re.split(r"(?m)^(?=##\s)", previous_report):
        m = re.match(r"^##\s*(.+)$", block.strip(), flags=re.M)
        if not m:
            continue
        title = m.group(1).strip().lower()
        for key, words in section_words.items():
            if key in result:
                continue
            if any(w in title for w in words):
                result[key] = block.strip()
                break
    return result


async def _generate_one_section(
    llm,
    *,
    topic: str,
    section: dict,
    template_id: str,
    template_focus: str,
    analysis_text: str,
    references_text: str,
    prior_outline: str,
    review_feedback: str | None = None,
    previous_section: str = "",
) -> str:
    """单次生成一个章节（短输出）；修订模式下基于上一版本章定向修改"""
    sys_parts = [
        "你是学术综述撰稿人。只输出本章节 Markdown 正文，"
        "不要输出整篇报告，不要其它章节，不要过程说明。",
        "引用只能使用提供的 [数字] 编号，禁止编造文献。",
    ]
    if previous_section:
        sys_parts.append(
            "你处于修订模式：下方提供该章节的上一版内容与审核修改意见。"
            "若修改意见涉及本章，输出修订后的本章全文（保留原有结构与准确内容，仅做针对性修改）；"
            "若与本章无关，原样输出上一版本章内容（不得改变实质内容与引用编号）。"
        )
    sys = SystemMessage(content="\n".join(sys_parts))
    fb = f"\n审核修改意见（本章针对性改进）：\n{review_feedback}\n" if review_feedback else ""
    prev = f"\n上一版本章内容：\n{previous_section[:2000]}\n" if previous_section else ""
    user = HumanMessage(
        content=(
            f"研究主题：{topic}\n"
            f"模板：{template_id} — {template_focus}\n"
            f"本章：{section['heading']}\n"
            f"要点：{section['hint']}；长度建议 ≤{section['max_chars']} 字\n"
            f"全文大纲（只作衔接）：{prior_outline}\n"
            f"分析数据节选：\n{analysis_text[:3500]}\n\n"
            f"可用引用：\n{references_text[:3000]}\n"
            f"{prev}"
            f"{fb}\n"
            f"直接输出该章节 Markdown。"
        )
    )
    resp = await llm.ainvoke([sys, user])
    return _strip_llm_preamble(str(resp.content or "").strip())


async def _write_report_sectioned(
    llm,
    *,
    topic: str,
    template_id: str,
    template_focus: str,
    analysis_text: str,
    references_text: str,
    review_feedback: str | None = None,
    previous_report: str = "",
) -> str:
    """按章节串行生成并拼装完整报告（修订模式下基于上一版定向修改）"""
    parts: list[str] = [f"# {topic}"]
    outline = " / ".join(s["heading"].replace("#", "").strip() for s in _REPORT_SECTIONS)
    prev_sections = (
        _split_previous_sections(previous_report) if review_feedback and previous_report else {}
    )

    for section in _REPORT_SECTIONS:
        prev_section = prev_sections.get(section["key"], "")
        text = ""
        for attempt in range(2):
            try:
                text = await _generate_one_section(
                    llm,
                    topic=topic,
                    section=section,
                    template_id=template_id,
                    template_focus=template_focus,
                    analysis_text=analysis_text,
                    references_text=references_text,
                    prior_outline=outline,
                    review_feedback=review_feedback if prev_section else None,
                    previous_section=prev_section,
                )
                if text:
                    break
            except Exception as e:
                logger.warning(f"章节 {section['key']} 第 {attempt + 1} 次失败: {e}")
                await asyncio.sleep(2)
        if not text:
            if prev_section:
                # 本节修订失败：保留上一版，不用占位符毁稿
                text = prev_section
            else:
                text = f"{section['heading']}\n\n（本节生成失败，已跳过）"
        if not text.lstrip().startswith("#"):
            text = f"{section['heading']}\n\n{text}"
        parts.append(text)
        await asyncio.sleep(0.4)

    return "\n\n".join(parts) + "\n"


async def writer_agent(state: dict) -> dict[str, Any]:
    """撰稿人节点 - 基于分析数据撰写/修改报告

    流程：
    1. 从 state 获取 analysis_data、topic、review_feedback
    2. 构建 prompt（包含分析数据和可能的修改意见）
    3. 调用 LLM 生成/修改报告
    4. 更新 report_draft 和 current_phase

    Args:
        state: AgentState 字典，包含 analysis_data、topic，可选 review_feedback

    Returns:
        包含 report_draft、current_phase、messages 的状态更新字典
    """
    topic = state["topic"]
    analysis_data = state.get("analysis_data", {})
    review_feedback = state.get("review_feedback")
    references = state.get("references", [])
    # 返工时上一版草稿仍在 state 中：修订模式以它为底稿定向修改，
    # 而不是拿同样的分析数据重新创作一份（旧实现的问题）
    previous_report = (state.get("report_draft") or "") if review_feedback else ""
    logger.info(f"撰稿人开始工作，主题: {topic}")

    # 上游已失败：短路透传
    if state.get("current_phase") == "failed":
        return {
            "report_draft": state.get("report_draft") or f"# {topic}\n\n> 任务失败",
            "current_phase": "failed",
            "messages": [HumanMessage(content="上游已失败，跳过撰稿")],
        }

    if review_feedback:
        if previous_report:
            logger.info(f"撰稿人进入修订模式：按修改意见分节修订（旧稿 {len(previous_report)} 字）")
        else:
            logger.info(f"撰稿人收到修改意见（无旧稿，按首写处理）: {review_feedback}")

    # ── 检查分析数据是否可用 ───────────────────────────────────
    if not analysis_data or analysis_data.get("error"):
        error_msg = analysis_data.get("error", "分析数据为空") if analysis_data else "分析数据为空"
        logger.warning(f"分析数据不可用: {error_msg}")
        # 失败终态：不进入人工审核
        return {
            "report_draft": f"# {topic}\n\n> 任务失败：{error_msg}",
            "current_phase": "failed",
            "messages": [HumanMessage(content=f"分析数据不可用: {error_msg}")],
        }

    # ── 将分析数据格式化为文本 ─────────────────────────────────
    analysis_text = _format_analysis_data(analysis_data)

    # ── 格式化引用列表 ─────────────────────────────────────────
    references_text = _format_references(references)

    # ── 初始化 LLM ──────────────────────────────────────────────
    llm_cfg = settings.resolve_llm_config(state.get("model_name"))
    llm = ChatOpenAI(
        model=llm_cfg["model"],
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        temperature=0.3,
        timeout=180,
        max_retries=2,
    )

    from backend.skills import load_skill_body, pick_report_template

    template_id, template_focus = pick_report_template(topic)
    skill_body = load_skill_body("report")
    if skill_body:
        logger.debug("已加载 report SKILL.md")

    # ── 分节撰稿：多次短调用拼装（降低中转站长请求 524）────────
    try:
        report_draft = await _write_report_sectioned(
            llm,
            topic=topic,
            template_id=template_id,
            template_focus=template_focus,
            analysis_text=analysis_text,
            references_text=references_text,
            review_feedback=review_feedback,
            previous_report=previous_report,
        )
        issues = _validate_report(report_draft)
        if issues:
            logger.warning(f"分节拼装后结构校验: {issues[:8]}")
        msg = HumanMessage(
            content="报告已按章节生成" if not review_feedback else "报告已按修改意见分节重写"
        )
        logger.info(f"撰稿人分节生成完成，长度: {len(report_draft)} 字符")
    except Exception as e:
        logger.error(f"撰稿人分节生成失败: {e}")
        if review_feedback and previous_report:
            # 修订失败保底：保留上一版报告并退回审核，不把旧稿覆盖成失败占位
            return {
                "report_draft": previous_report,
                "final_report": previous_report,
                "current_phase": "reviewing",
                "messages": [HumanMessage(content=f"本次修改失败，已保留上一版：{e}")],
            }
        return {
            "report_draft": f"# {topic}\n\n> 任务失败：LLM 调用错误 - {e}",
            "current_phase": "failed",
            "messages": [HumanMessage(content=f"撰稿人调用失败: {e}")],
        }

    # ── 正文引用编号与文献列表对账（只保留真实文献）────────────
    from backend.skills import validate_report_structure
    from backend.utils.citations import reconcile_references
    from backend.utils.quality import quality_score_report

    report_draft, real_refs, cite_issues = reconcile_references(report_draft, references)
    if cite_issues:
        logger.warning(f"引用对账: {cite_issues}")

    struct_issues = validate_report_structure(report_draft)
    q_rep = quality_score_report(report_draft, real_refs)
    if struct_issues:
        logger.warning(f"结构校验: {struct_issues[:8]}")
    if q_rep.get("score", 1.0) < 0.45:
        logger.warning(f"报告质量分偏低 {q_rep}（分节拼装已尽力，保留结果）")

    return {
        "report_draft": report_draft,
        "current_phase": "reviewing",
        "references": real_refs,
        "quality_metrics": {"report": q_rep},
        "messages": [msg],
    }


def _format_analysis_data(analysis_data: dict[str, Any]) -> str:
    """将分析数据字典格式化为可读文本

    支持两种情况：
    - 结构化 JSON 数据（正常流程）
    - raw_analysis 原始文本（JSON 解析失败时的回退）

    Args:
        analysis_data: 分析师输出的数据字典

    Returns:
        格式化后的文本字符串
    """
    # 如果是原始文本回退模式
    if "raw_analysis" in analysis_data:
        return f"分析师原始输出（未解析为结构化数据）：\n\n{analysis_data['raw_analysis']}"

    # 结构化数据 → 按维度格式化
    parts: list[str] = []

    section_labels = {
        "field_overview": "领域概况",
        "method_categories": "方法分类",
        "performance_comparison": "性能对比",
        "timeline_analysis": "发展脉络",
        "research_groups": "研究团队",
        "challenges_and_gaps": "挑战与研究空白",
        "key_findings": "核心发现",
        "data_sources": "数据来源",
    }

    for key, label in section_labels.items():
        value = analysis_data.get(key)
        if value is not None:
            if isinstance(value, dict):
                formatted = json.dumps(value, ensure_ascii=False, indent=2)
            elif isinstance(value, list):
                formatted = json.dumps(value, ensure_ascii=False, indent=2)
            else:
                formatted = str(value)
            parts.append(f"## {label}\n{formatted}")

    return "\n\n---\n\n".join(parts) if parts else "暂无结构化分析数据"


def _format_references(references: list[dict[str, Any]]) -> str:
    """将引用列表格式化为可读文本

    Args:
        references: 引用条目列表，每个条目包含 id、title、url、source、date

    Returns:
        格式化后的引用文本字符串
    """
    if not references:
        return "暂无引用来源"

    parts: list[str] = []
    for ref in references:
        ref_id = ref.get("id", "?")
        title = ref.get("title", "未知来源")
        url = ref.get("url", "")
        source = ref.get("source", "")
        date = ref.get("date", "")
        journal = ref.get("journal", "")
        bits = [b for b in (journal, source, date) if b]
        line = f"[{ref_id}] {title}"
        if bits:
            line += f" ({' · '.join(bits)})"
        if url:
            line += f" - {url}"
        parts.append(line)

    return "\n".join(parts)


def _strip_llm_preamble(text: str) -> str:
    """清洗撰稿输出：去掉自言自语、拼接的重复报告、乱码后重贴的整篇

    实测问题（MAMBA 任务）：
    - 正文前有“所有关键文献已核实完毕…”
    - 中途出现“以下为修正后的完整报告”后又整篇重贴
    - 参考文献章节重复多次
    """
    import re

    if not text:
        return text

    # 1) 若包含“修正后重新输出/完整报告”分段，优先取最后一段干净正文
    split_markers = [
        r"以下为修正后的完整报告",
        r"修正后的完整报告",
        r"重新输出的完整报告",
        r"去除乱码后重新输出",
    ]
    for marker in split_markers:
        parts = re.split(marker, text)
        if len(parts) >= 2:
            tail = parts[-1].lstrip("：:\n\r-— ")
            # 去掉可能残留的分隔线
            tail = re.sub(r"^-{3,}\s*$", "", tail, flags=re.M).strip()
            if tail.lstrip().startswith("#"):
                text = tail
                break

    # 2) 从第一个 Markdown 标题开始
    stripped = text.lstrip()
    if not stripped.startswith("#"):
        m = re.search(r"(?m)^#{1,2}\s+\S", text)
        if m:
            text = text[m.start():].lstrip()
        else:
            m = re.search(r"(?m)^---\s*$", text)
            if m:
                tail = text[m.end():].lstrip()
                if tail.startswith("#"):
                    text = tail

    # 3) 多个一级标题时，只保留第一篇（避免整篇报告被重贴拼接）
    lines = text.splitlines()
    h1_idx = [i for i, ln in enumerate(lines) if ln.startswith("# ")]
    if len(h1_idx) >= 2:
        text = "\n".join(lines[: h1_idx[1]]).rstrip() + "\n"

    # 4) 参考文献章节只保留第一次出现
    refs = list(re.finditer(r"(?m)^##\s*(参考文献|References)\s*$", text))
    if len(refs) >= 2:
        text = text[: refs[1].start()].rstrip() + "\n"

    return text.strip() + ("\n" if text.strip() else "")


def _validate_report(text: str) -> list[str]:
    """检测撰稿输出的硬伤，返回问题列表（空列表表示通过）"""
    import re

    issues: list[str] = []
    if not text or not text.strip():
        return ["报告为空"]

    body = text.strip()
    if not body.startswith("#"):
        issues.append("未以 Markdown 标题开头")

    h1_count = len(re.findall(r"(?m)^#\s+\S", body))
    if h1_count >= 2:
        issues.append(f"一级标题重复 {h1_count} 次（疑似整篇重贴）")

    for pat, label in (
        (r"(?m)^##\s*摘要", "摘要章节"),
        (r"(?m)^##\s*(参考文献|References)", "参考文献章节"),
    ):
        n = len(re.findall(pat, body))
        if n >= 2:
            issues.append(f"{label}重复 {n} 次")

    process_markers = (
        "已核实完毕",
        "以下是完整的文献综述报告",
        "修正后的完整报告",
        "去除乱码后重新输出",
    )
    for m in process_markers:
        if m in body:
            issues.append(f"仍含过程说明：{m}")

    if "�" in body:
        issues.append("含 Unicode 替换字符（乱码）")
    # 异常控制字符（保留 \n\t）
    ctrl = re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", body)
    if len(ctrl) >= 3:
        issues.append(f"含 {len(ctrl)} 个异常控制字符")

    return issues
