"""数据可视化工具 - 使用 matplotlib 生成静态 PNG 图表

本模块提供三个 LangChain 工具：
- generate_trend_chart: 趋势折线图
- generate_competition_chart: 竞争格局饼图/柱状图
- generate_comparison_chart: 多维度对比柱状图
"""
import json
import logging
import os
from contextvars import ContextVar
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # 非交互后端，必须在 import pyplot 之前

import matplotlib.pyplot as plt
import numpy as np
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── 中文字体配置 ─────────────────────────────────────────────────
# Windows: SimHei；Linux 服务器: WenQuanYi Zen Hei / Noto Sans CJK SC（部署时安装字体即可）
plt.rcParams["font.sans-serif"] = ["SimHei", "WenQuanYi Zen Hei", "Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# ── 图表输出目录 ─────────────────────────────────────────────────
CHARTS_DIR = Path(__file__).parent.parent.parent / "output" / "charts"

# 当前研究 thread_id：图表按任务分子目录，避免多任务串图/互相覆盖
# asyncio.to_thread 会拷贝 context，线程池内工具仍能读到
_chart_thread_id: ContextVar[str] = ContextVar("chart_thread_id", default="")


def set_chart_thread_id(thread_id: str) -> None:
    """由分析师节点在调用绘图工具前设置，用于隔离图表目录"""
    _chart_thread_id.set(thread_id or "")


def _ensure_charts_dir() -> Path:
    """确保当前任务的图表目录存在（output/charts/<thread_id>/）"""
    tid = _chart_thread_id.get().strip()
    # 仅保留安全字符，防止路径注入
    safe_tid = "".join(c if c.isalnum() or c in "-_" else "_" for c in tid) or "misc"
    target = CHARTS_DIR / safe_tid
    target.mkdir(parents=True, exist_ok=True)
    return target


def _save_chart(fig: plt.Figure, chart_name: str) -> str:
    """保存图表到当前任务子目录并返回路径"""
    out_dir = _ensure_charts_dir()
    # 清理文件名中的非法字符
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in chart_name)
    safe_name = safe_name.strip().replace(" ", "_")
    if not safe_name:
        safe_name = "chart"
    filepath = out_dir / f"{safe_name}.png"
    fig.savefig(str(filepath), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(filepath)


@tool
def generate_trend_chart(data_json: str, chart_name: str) -> str:
    """生成趋势折线图。输入 JSON 格式数据和图表名称，返回生成的图表文件路径。

    Args:
        data_json: JSON 字符串，格式为：
            {
                "title": "图表标题",
                "x_label": "X轴标签",
                "y_label": "Y轴标签",
                "series": [
                    {"name": "系列名", "x": [1, 2, 3], "y": [10, 20, 30]},
                    ...
                ]
            }
        chart_name: 图表名称，用于生成文件名

    Returns:
        生成的 PNG 图表文件路径字符串，或错误信息字符串。
    """
    try:
        data = json.loads(data_json)
        title = data.get("title", chart_name)
        x_label = data.get("x_label", "")
        y_label = data.get("y_label", "")
        series_list = data.get("series", [])

        if not series_list:
            return "错误：series 数据为空，无法生成趋势图"

        fig, ax = plt.subplots(figsize=(10, 6))
        for s in series_list:
            name = s.get("name", "未命名")
            x = s.get("x", list(range(len(s.get("y", [])))))
            y = s.get("y", [])
            ax.plot(x, y, marker="o", label=name, linewidth=2)

        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.legend()
        ax.grid(True, alpha=0.3)

        filepath = _save_chart(fig, chart_name)
        logger.info(f"趋势图已生成: {filepath}")
        return f"图表已生成: {filepath}"

    except json.JSONDecodeError as e:
        logger.error(f"趋势图 JSON 解析失败: {e}")
        return f"错误：JSON 数据解析失败 - {e}"
    except Exception as e:
        logger.error(f"趋势图生成失败: {e}", exc_info=True)
        return f"错误：生成趋势图失败 - {e}"


@tool
def generate_competition_chart(data_json: str, chart_name: str) -> str:
    """生成竞争格局饼图或柱状图。输入 JSON 格式数据和图表名称，返回生成的图表文件路径。

    Args:
        data_json: JSON 字符串，格式为：
            {
                "title": "图表标题",
                "chart_type": "pie" 或 "bar"（默认 pie）,
                "items": [
                    {"name": "公司A", "value": 35},
                    {"name": "公司B", "value": 25},
                    ...
                ]
            }
        chart_name: 图表名称，用于生成文件名

    Returns:
        生成的 PNG 图表文件路径字符串，或错误信息字符串。
    """
    try:
        data = json.loads(data_json)
        title = data.get("title", chart_name)
        chart_type = data.get("chart_type", "pie")
        items = data.get("items", [])

        if not items:
            return "错误：items 数据为空，无法生成竞争格局图"

        names = [item.get("name", "未知") for item in items]
        values = [item.get("value", 0) for item in items]

        fig, ax = plt.subplots(figsize=(10, 6))

        if chart_type == "bar":
            x_pos = np.arange(len(names))
            bars = ax.bar(x_pos, values, color=plt.cm.Set3(np.linspace(0, 1, len(names))))
            ax.set_xticks(x_pos)
            ax.set_xticklabels(names, rotation=45, ha="right")
            # 在柱状图上方显示数值
            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"{val}", ha="center", va="bottom", fontsize=9)
            ax.set_ylabel("数值")
        else:
            # 默认饼图
            colors = plt.cm.Set3(np.linspace(0, 1, len(names)))
            wedges, texts, autotexts = ax.pie(
                values, labels=names, autopct="%1.1f%%",
                colors=colors, startangle=90
            )
            for text in autotexts:
                text.set_fontsize(9)
            ax.set_aspect("equal")

        ax.set_title(title, fontsize=14, fontweight="bold")

        filepath = _save_chart(fig, chart_name)
        logger.info(f"竞争格局图已生成: {filepath}")
        return f"图表已生成: {filepath}"

    except json.JSONDecodeError as e:
        logger.error(f"竞争格局图 JSON 解析失败: {e}")
        return f"错误：JSON 数据解析失败 - {e}"
    except Exception as e:
        logger.error(f"竞争格局图生成失败: {e}", exc_info=True)
        return f"错误：生成竞争格局图失败 - {e}"


@tool
def generate_comparison_chart(data_json: str, chart_name: str) -> str:
    """生成多维度对比柱状图。输入 JSON 格式数据和图表名称，返回生成的图表文件路径。

    Args:
        data_json: JSON 字符串，格式为：
            {
                "title": "图表标题",
                "categories": ["维度1", "维度2", ...],
                "groups": [
                    {"name": "对象A", "values": [80, 90, 70, ...]},
                    {"name": "对象B", "values": [60, 85, 95, ...]},
                    ...
                ]
            }
        chart_name: 图表名称，用于生成文件名

    Returns:
        生成的 PNG 图表文件路径字符串，或错误信息字符串。
    """
    try:
        data = json.loads(data_json)
        title = data.get("title", chart_name)
        categories = data.get("categories", [])
        groups = data.get("groups", [])

        if not categories or not groups:
            return "错误：categories 或 groups 数据为空，无法生成对比图"

        n_categories = len(categories)
        n_groups = len(groups)
        x = np.arange(n_categories)
        width = 0.8 / n_groups  # 每组柱子的宽度

        fig, ax = plt.subplots(figsize=(12, 6))
        colors = plt.cm.Set2(np.linspace(0, 1, n_groups))

        for i, group in enumerate(groups):
            name = group.get("name", f"组{i+1}")
            values = group.get("values", [0] * n_categories)
            offset = (i - n_groups / 2 + 0.5) * width
            bars = ax.bar(x + offset, values, width, label=name, color=colors[i])
            # 在柱子上方显示数值
            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        f"{val}", ha="center", va="bottom", fontsize=8)

        ax.set_xticks(x)
        ax.set_xticklabels(categories, rotation=45, ha="right")
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.legend()
        ax.grid(True, axis="y", alpha=0.3)

        fig.tight_layout()
        filepath = _save_chart(fig, chart_name)
        logger.info(f"对比柱状图已生成: {filepath}")
        return f"图表已生成: {filepath}"

    except json.JSONDecodeError as e:
        logger.error(f"对比柱状图 JSON 解析失败: {e}")
        return f"错误：JSON 数据解析失败 - {e}"
    except Exception as e:
        logger.error(f"对比柱状图生成失败: {e}", exc_info=True)
        return f"错误：生成对比柱状图失败 - {e}"
