"""定位「重要契約」段落的測試。需要一份真實 PDF 才能跑,預設會跳過。

要實際測試,把任一份年報 PDF 放到 data/raw_pdfs/,然後:
    PDF_FOR_TEST=data/raw_pdfs/2303_2023.pdf pytest tests/test_locate_contracts.py -v
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.extract.locate_contracts import locate

PDF_FOR_TEST = os.environ.get("PDF_FOR_TEST")


@pytest.mark.skipif(not PDF_FOR_TEST, reason="設定環境變數 PDF_FOR_TEST 指向一份年報 PDF 才會跑這個測試")
def test_locate_finds_section():
    result = locate(PDF_FOR_TEST)
    assert result is not None
    assert len(result.pages) >= 1
    assert "契約" in result.text
