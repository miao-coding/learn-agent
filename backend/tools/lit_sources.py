"""高质量学术文献源（服务器实测可用）

实测结论（国内 1.6G 服务器）：
- Crossref / OpenAlex / EuropePMC / CORE：可达，适合做主检索
- ArXiv：可达但有限流
- Semantic Scholar：无 Key 易 429
- DuckDuckGo / Wikipedia：网络不可达（仅作可选弱源）
"""
from __future__ import annotations

import logging
import re
from typing import Any

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "learn-agent/1.0 (academic-research-bot)"}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _fmt_entry(i: int, title: str, authors: str, year: Any, cited: Any,
               url: str, doi: str, source: str, abstract: str = "") -> str:
    parts = [f"[{i}] {_clean(title)[:180]}"]
    if authors:
        parts.append(f"    作者: {authors[:160]}")
    meta = []
    if year:
        meta.append(f"年份: {year}")
    if cited is not None:
        meta.append(f"被引: {cited}")
    if doi:
        meta.append(f"DOI: {doi}")
    meta.append(f"来源库: {source}")
    parts.append("    " + " | ".join(meta))
    if url:
        parts.append(f"    URL: {url}")
    if abstract:
        parts.append(f"    摘要: {_clean(abstract)[:420]}")
    return "\n".join(parts) + "\n"


def _crossref_search_impl(query: str, max_results: int = 8) -> str:
    q = _clean(query)
    if not q:
        return "错误：查询为空"
    try:
        n = max(1, min(int(max_results or 8), 15))
        resp = requests.get(
            "https://api.crossref.org/works",
            params={
                "query.bibliographic": q,
                "rows": n,
                "filter": "type:journal-article",
                "select": "title,DOI,published-print,published-online,URL,author,abstract,is-referenced-by-count",
            },
            headers=_UA,
            timeout=15,
        )
        resp.raise_for_status()
        items = (resp.json() or {}).get("message", {}).get("items") or []
        if not items:
            return "未找到相关学术论文"

        lines = []
        for i, it in enumerate(items, 1):
            title = (it.get("title") or [""])[0]
            doi = it.get("DOI") or ""
            url = it.get("URL") or (f"https://doi.org/{doi}" if doi else "")
            authors = ", ".join(
                _clean(f"{a.get('given', '')} {a.get('family', '')}").strip()
                for a in (it.get("author") or [])[:4]
                if a
            )
            pub = it.get("published-print") or it.get("published-online") or {}
            parts = pub.get("date-parts") or [[None]]
            year = (parts[0] or [None])[0]
            cited = it.get("is-referenced-by-count")
            abstract = ""
            if it.get("abstract"):
                abstract = re.sub(r"<[^>]+>", " ", str(it["abstract"]))
            lines.append(_fmt_entry(i, title, authors, year, cited, url, doi, "crossref", abstract))
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Crossref 搜索失败: {e}")
        return f"Crossref 搜索失败: {e}"


def _openalex_search_impl(query: str, max_results: int = 8, from_year: int = 0) -> str:
    q = _clean(query)
    if not q:
        return "错误：查询为空"
    try:
        n = max(1, min(int(max_results or 8), 15))
        filters = ["type:article|review"]
        if from_year and int(from_year) > 1900:
            filters.append(f"from_publication_date:{int(from_year)}-01-01")
        filt = ",".join(filters)
        resp = requests.get(
            "https://api.openalex.org/works",
            params={
                "filter": f"{filt},title_and_abstract.search:{q}",
                "per-page": n,
                "sort": "cited_by_count:desc",
            },
            headers=_UA,
            timeout=18,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
        if not results:
            resp = requests.get(
                "https://api.openalex.org/works",
                params={"search": q, "per-page": n, "filter": filt},
                headers=_UA,
                timeout=18,
            )
            resp.raise_for_status()
            results = (resp.json() or {}).get("results") or []
        if not results:
            return "未找到相关学术论文"

        lines = []
        for i, w in enumerate(results, 1):
            title = w.get("title") or w.get("display_name") or ""
            year = w.get("publication_year")
            cited = w.get("cited_by_count")
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            loc = w.get("primary_location") or {}
            src_name = ((loc.get("source") or {}).get("display_name")) or ""
            oa = (w.get("open_access") or {}).get("oa_url") or ""
            url = oa or loc.get("landing_page_url") or (w.get("doi") or "")
            authors = []
            for a in (w.get("authorships") or [])[:4]:
                name = (a.get("author") or {}).get("display_name")
                if name:
                    authors.append(name)
            abstract = ""
            inv = w.get("abstract_inverted_index") or {}
            if inv:
                pairs = []
                for word, positions in inv.items():
                    for pos in positions:
                        pairs.append((pos, word))
                pairs.sort()
                abstract = " ".join(w for _, w in pairs)[:420]
            extra = src_name or "openalex"
            lines.append(_fmt_entry(i, title, ", ".join(authors), year, cited, url, doi, extra, abstract))
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"OpenAlex 搜索失败: {e}")
        return f"OpenAlex 搜索失败: {e}"


def _europepmc_search_impl(query: str, max_results: int = 6) -> str:
    q = _clean(query)
    if not q:
        return "错误：查询为空"
    try:
        n = max(1, min(int(max_results or 6), 12))
        resp = requests.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": q, "format": "json", "pageSize": n, "resultType": "core"},
            headers=_UA,
            timeout=15,
        )
        resp.raise_for_status()
        results = ((resp.json() or {}).get("resultList") or {}).get("result") or []
        if not results:
            return "未找到相关学术论文"

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title") or ""
            year = r.get("pubYear")
            cited = r.get("citedByCount")
            doi = r.get("doi") or ""
            url = f"https://doi.org/{doi}" if doi else (
                f"https://europepmc.org/article/{r.get('source', 'MED')}/{r.get('id', '')}"
                if r.get("id") else ""
            )
            authors = r.get("authorString") or ""
            abstract = r.get("abstractText") or ""
            lines.append(_fmt_entry(i, title, authors, year, cited, url, doi, "europepmc", abstract))
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"EuropePMC 搜索失败: {e}")
        return f"EuropePMC 搜索失败: {e}"


def _core_search_impl(query: str, max_results: int = 6) -> str:
    q = _clean(query)
    if not q:
        return "错误：查询为空"
    try:
        n = max(1, min(int(max_results or 6), 12))
        resp = requests.get(
            "https://api.core.ac.uk/v3/search/works",
            params={"q": q, "limit": n},
            headers=_UA,
            timeout=18,
        )
        if resp.status_code in (401, 403):
            return "CORE 搜索失败: 需要 API Key 或配额不足"
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
        if not results:
            return "未找到相关学术论文"

        lines = []
        for i, w in enumerate(results, 1):
            title = w.get("title") or ""
            year = w.get("yearPublished") or (w.get("publishedDate") or "")[:4]
            cited = w.get("citationCount")
            doi = w.get("doi") or ""
            url = w.get("downloadUrl") or w.get("sourceFulltextUrls") or w.get("links") or ""
            if isinstance(url, list):
                url = url[0] if url else ""
            if not url and doi:
                url = f"https://doi.org/{doi}"
            authors = ", ".join(a.get("name", "") for a in (w.get("authors") or [])[:4])
            abstract = w.get("abstract") or ""
            lines.append(_fmt_entry(i, title, authors, year, cited, str(url), doi, "core", abstract))
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"CORE 搜索失败: {e}")
        return f"CORE 搜索失败: {e}"


@tool
def crossref_search(query: str, max_results: int = 8) -> str:
    """Crossref 学术检索（无需 Key，服务器实测稳定）。优先返回期刊论文，适合文献综述主源。

    Args:
        query: 研究主题（英文关键词效果更好）
        max_results: 返回条数，默认 8
    """
    return _crossref_search_impl(query, max_results)


@tool
def openalex_search(query: str, max_results: int = 8, from_year: int = 0) -> str:
    """OpenAlex 学术检索（无需 Key）。按被引排序，可限制起始年份。

    Args:
        query: 研究主题关键词
        max_results: 返回条数，默认 8
        from_year: 起始年份（如 2018；0 表示不限）
    """
    return _openalex_search_impl(query, max_results, from_year)


@tool
def europepmc_search(query: str, max_results: int = 6) -> str:
    """Europe PMC 学术检索（无需 Key，服务器实测稳定）。

    Args:
        query: 研究主题
        max_results: 返回条数，默认 6
    """
    return _europepmc_search_impl(query, max_results)


@tool
def core_search(query: str, max_results: int = 6) -> str:
    """CORE 学术开放获取检索（无需 Key，实测可达）。

    Args:
        query: 研究主题
        max_results: 返回条数，默认 6
    """
    return _core_search_impl(query, max_results)


@tool
def academic_fallback_search(query: str, max_results: int = 8) -> str:
    """按可靠性依次尝试 Crossref → OpenAlex → EuropePMC → CORE（无需 Key）。

    任一源成功即返回，避免单一源失败导致无文献。适合作为检索主工具。

    Args:
        query: 研究主题
        max_results: 目标条数，默认 8
    """
    q = _clean(query)
    if not q:
        return "错误：查询为空"
    n = max(1, min(int(max_results or 8), 12))
    attempts = (
        ("Crossref", _crossref_search_impl),
        ("OpenAlex", _openalex_search_impl),
        ("EuropePMC", _europepmc_search_impl),
        ("CORE", _core_search_impl),
    )
    logs = []
    for name, fn in attempts:
        try:
            out = fn(q, n)
        except Exception as e:
            logs.append(f"{name}: {e}")
            continue
        text = str(out or "")
        if text and not text.startswith(("未找到", f"{name} 搜索失败", "错误")):
            logger.info(f"academic_fallback 命中 {name}")
            return text + f"\n\n（来源: {name}）"
        logs.append(f"{name}: {text[:80]}")
    return "未找到相关学术论文；各源情况：" + "；".join(logs[:4])
