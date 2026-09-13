"""文献真实性：多条目拆分、收录门槛、重编号与对账"""
from backend.utils.citations import (
    build_references_from_search_results,
    extract_reference_meta,
    reconcile_references,
    split_search_result_entries,
)


SAMPLE_ARXIV_BLOCK = """
[1] ChangeMamba: Visual State Space Model for Change Detection
    作者: A, B
    日期: 2024-03-01
    arXiv ID: 2403.00123
    摘要: ...
[2] A Survey on Visual Mamba
    作者: C
    日期: 2024-01-15
    arXiv ID: 2401.05555
    摘要: ...
[3] MambaHSI: Spatial Spectral Mamba
    作者: D
    日期: 2023-11-01
    arXiv ID: 2311.01234
    摘要: ...
"""


def test_split_multiple_arxiv_entries():
    parts = split_search_result_entries(SAMPLE_ARXIV_BLOCK)
    assert len(parts) == 3
    assert "ChangeMamba" in parts[0]
    assert "Survey" in parts[1]


def test_build_refs_from_multi_entry_block():
    results = [
        {"source": "arxiv", "query": "mamba remote sensing", "content": SAMPLE_ARXIV_BLOCK}
    ]
    refs = build_references_from_search_results(results)
    assert len(refs) == 3
    assert refs[0]["id"] == 1
    assert "arxiv.org/abs/2403.00123" in refs[0]["url"]
    assert "ChangeMamba" in refs[0]["title"]


def test_query_is_not_used_as_title():
    meta = extract_reference_meta("arxiv", "未找到相关学术论文", "mamba remote sensing")
    assert meta["title"] == ""  # 不再用 query 冒充


def test_reconcile_renumbers_and_strips_fabricated():
    report = (
        "# 综述\n\n方法 A [3] 方法 B [9] 方法 C [1]\n\n"
        "## 参考文献\n\n[3] Fake Third\n[9] Fake Ninth\n[1] Fake First\n"
    )
    # 真实检索：原 id 1 和 3
    refs = [
        {"id": 1, "title": "Real Paper Alpha", "url": "https://doi.org/10.1/a", "source": "crossref", "date": "2020"},
        {"id": 3, "title": "Real Paper Gamma", "url": "https://arxiv.org/abs/2401.0001", "source": "arxiv", "date": "2024"},
    ]
    cleaned, real, issues = reconcile_references(report, refs)

    # [9] 编造 → 删除；[1]/[3] 重编号为 [1]/[2] 保持正文语义映射
    body = cleaned.split("## 参考文献")[0]
    assert "[9]" not in body
    assert "[2]" in body  # 原 3 → 2
    assert "Real Paper Alpha" in cleaned
    assert "Fake" not in cleaned
    assert len(real) == 2
    assert [r["id"] for r in real] == [1, 2]


def test_reconcile_drops_placeholder_titles():
    report = "# T\n\n内容 [1][2]\n"
    refs = [
        {"id": 1, "title": "未命名来源（正文引用但检索列表缺失）", "url": "", "source": "unknown", "date": ""},
        {"id": 2, "title": "Genuine Long Paper Title About Mamba", "url": "https://x.example/p", "source": "scholar", "date": "2024"},
    ]
    cleaned, real, _ = reconcile_references(report, refs)
    assert all("未命名" not in r["title"] for r in real)
    assert len(real) == 1
    assert "[1]" in cleaned.split("## 参考文献")[0]
    assert "Genuine Long Paper Title" in cleaned
