"""图表按任务隔离，避免多任务串图"""
import json
from pathlib import Path
from unittest.mock import patch

from backend.tools.visualization import generate_trend_chart, set_chart_thread_id


def _invoke(title: str):
    data = json.dumps(
        {
            "title": title,
            "series": [{"name": "s", "x": [1, 2], "y": [1, 2]}],
        }
    )
    return generate_trend_chart.invoke({"data_json": data, "chart_name": title})


def test_charts_saved_under_thread_subdir(tmp_path):
    set_chart_thread_id("thread-abc")
    with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
        result = _invoke("隔离测试")
    assert "thread-abc" in result
    path = Path(result.split("图表已生成:")[-1].strip())
    assert path.exists()
    assert path.parent.name == "thread-abc"


def test_different_threads_do_not_share_dir(tmp_path):
    with patch("backend.tools.visualization.CHARTS_DIR", tmp_path):
        set_chart_thread_id("t1")
        r1 = _invoke("T1")
        set_chart_thread_id("t2")
        r2 = _invoke("T2")
    p1 = Path(r1.split("图表已生成:")[-1].strip())
    p2 = Path(r2.split("图表已生成:")[-1].strip())
    assert p1.parent != p2.parent
    assert p1.exists() and p2.exists()


def test_frontend_does_not_glob_all_charts():
    """回归：图表 Tab 不得扫描全局 output/charts/*.png"""
    import inspect

    from frontend import app as fe

    src = inspect.getsource(fe._render_charts_tab)
    assert "glob.glob" not in src
    assert "charts" in src
