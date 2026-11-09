"""
分析「一份」年報 PDF 的完整步驟,一鍵更新(GitHub Actions)跟網頁上的
「手動上傳年報」都呼叫這裡,確保兩邊結果一模一樣。

回傳 (狀態, 待檢查資料列, 說明)。狀態定義在 config/schema.py。
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
import uuid
from pathlib import Path

import fitz  # pymupdf

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from config.schema import (  # noqa: E402
    STATUS_NO_CONTRACT, STATUS_NO_RD, STATUS_NOT_FOUND_SECTION, STATUS_OK,
)
from src.extract.locate_contracts import locate  # noqa: E402

COMPANY_SUFFIX_RE = re.compile(
    r"([一-鿿]{2,20}(?:股份有限公司|企業股份有限公司|工業股份有限公司|投資控股股份有限公司))"
)

FIELD_MAP_EN_TO_ZH = {
    "party_b_code": "乙方代碼", "party_b_full_name": "乙方全稱", "party_b_short_name": "乙方簡稱",
    "party_b_country": "乙方國", "party_b_org_type": "乙方機構類別", "party_b_is_tw_listed": "乙方是否在台公發",
    "contract_content": "合作契約內容", "contract_note": "合作契約備註", "contract_type": "合作契約類別",
    "is_rd_cooperation": "合作契約R&D與否", "direction_code": "是否有合作方向",
    "start_year": "合作契約起年", "end_year": "合作契約訖年",
    "has_termination_clause": "是否有終止條件", "termination_clause": "合作契約終止條件",
    "has_confidentiality_clause": "是否有保密條款", "restriction_clause": "限制條款",
}


def guess_company_name(pdf_path: Path) -> str | None:
    """從 PDF 前幾頁抓「XXX股份有限公司」當甲方全稱。
    公司改名、併購時每年封面名字會跟著變,讀當年封面比維護固定名單更準。
    有些封面是純圖片沒有文字,所以往後多找幾頁(目錄頁通常有)。"""
    doc = fitz.open(str(pdf_path))
    for page in doc[:5]:
        m = COMPANY_SUFFIX_RE.search(unicodedata.normalize("NFKC", page.get_text()))
        if m:
            return m.group(1)
    return None


def analyze_pdf(pdf_path: Path, stock_code: str, report_year: int, *,
                source_link: str = "", company_name: str | None = None,
                company_short: str | None = None, extractor=None) -> tuple[str, list[dict], str]:
    """extractor 預設是 Gemini(llm_extract.extract);測試時可以換成假的。"""
    if extractor is None:
        from src.extract.llm_extract import extract as extractor

    section = locate(str(pdf_path))
    if section is None:
        return STATUS_NOT_FOUND_SECTION, [], "PDF 裡找不到「重要契約」文字,可能是掃描圖檔,請人工看"
    pages = ",".join(str(p + 1) for p in section.pages)
    if section.likely_no_contract:
        return STATUS_NO_CONTRACT, [], f"原文聲明無重要契約(第 {pages} 頁)"

    result = extractor(section.text)
    if not result.has_any_contract or not result.contracts:
        return STATUS_NO_RD, [], f"重要契約裡沒有研發合作相關契約(第 {pages} 頁)"

    name = company_name or guess_company_name(pdf_path) or f"(未知,股票代碼{stock_code})"
    short = company_short or name
    created = (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")

    rows = []
    for c in result.contracts:
        if getattr(c, "is_rd_cooperation", 1) == 0:
            continue  # 保險:模型萬一把非研發合作的也列出來,這裡再擋一次
        row = {
            "紀錄ID": uuid.uuid4().hex[:12],
            "甲方代碼": stock_code, "甲方全稱": name, "甲方簡稱": short,
            "甲方機構類別": "公司", "甲方是否在台公發": 1,
            "合作契約所屬年報年份": report_year,
            "來源連結": source_link, "來源頁碼": pages,
            "AI信心": c.confidence, "AI信心說明": c.confidence_note or "",
            "建立時間": created,
        }
        for en, zh in FIELD_MAP_EN_TO_ZH.items():
            row[zh] = getattr(c, en)
        rows.append(row)

    if not rows:
        return STATUS_NO_RD, [], f"重要契約裡沒有研發合作相關契約(第 {pages} 頁)"
    return STATUS_OK, rows, f"抽出 {len(rows)} 筆(第 {pages} 頁)"
