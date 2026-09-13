"""上传文献抽取"""
from pathlib import Path

from backend.utils.upload_docs import (
    extract_reference_titles,
    ingest_uploaded_file,
    load_upload_batch,
    uploads_to_search_seed,
)


def test_extract_reference_titles_from_tail():
    text = (
        "Some paper body\n" * 20
        + "\nReferences\n"
        + "[1] ChangeMamba: Visual State Space Model for Remote Sensing Change Detection\n"
        + "[2] A Survey on Visual Mamba in Computer Vision\n"
        + "short\n"
    )
    titles = extract_reference_titles(text)
    assert len(titles) >= 2
    assert "ChangeMamba" in titles[0]


def test_ingest_txt_and_seed():
    body = "Title Line About Mamba Remote Sensing\n\n" + ("content " * 100) + "\nReferences\n[1] Long Enough Citation Title Here For Test\n"
    meta = ingest_uploaded_file("sample.txt", body.encode("utf-8"))
    assert meta and meta["text_chars"] > 50
    seeds = uploads_to_search_seed(meta["batch_id"])
    assert any(s["source"] == "uploaded" for s in seeds)
    assert load_upload_batch(meta["batch_id"]) is not None
