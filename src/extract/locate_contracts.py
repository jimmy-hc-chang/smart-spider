"""
從整本年報 PDF 裡,找出「重要契約」那一段的文字,不用把兩三百頁全部
丟給 LLM。

做法:全文搜尋「重要契約」關鍵字所在頁,但年報通常在目錄頁也會列出
「重要契約」這幾個字(當作章節標題+頁碼),所以不能抓「第一個出現
的頁」,而是要在所有出現關鍵字的頁面裡,挑「契約」相關字樣密度最高
的那一頁當錨點(目錄頁密度低,正文表格頁密度高),再往後抓續頁。

【重要 bug 修正記錄,寫給以後維護的人看】
早期版本直接用 `'重要契約' in page_text` 判斷,結果在好幾家公司的
PDF 上完全抓錯頁(抓到目錄頁,或甚至抓不到)。追查後發現:部分
Word/InDesign 匯出的 PDF,中文字用的是 Unicode「CJK 相容表意文字」
區塊(U+F900-U+FAFF)的碼位,長得跟正常字一模一樣,但碼位不同,例如
「契」字在某些字型裡實際編碼是 U+F909 而不是標準的 U+5951,導致字串
比對永遠比不中。解法是先用 unicodedata.normalize('NFKC', text) 把這
些相容碼位轉回標準碼位,再做關鍵字比對。這個問題不只影響「重要契約」
四個字,理論上任何關鍵字比對(公司名稱、地名等)都可能中招,如果之後
遇到「明明肉眼看得到字,程式卻比對不到」的情況,先檢查是不是這個原因。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import fitz  # pymupdf

SECTION_KEYWORD = "重要契約"
CONTINUATION_HINTS = ("契約性質", "契約對象", "限制條款", "主要內容", "重要契約")
NO_CONTRACT_PATTERNS = ("並無簽訂重要契約", "無重要契約", "尚無重要契約")
MAX_CONTINUATION_PAGES = 6  # 保護措施,避免關鍵字誤判導致抓到一整本書
TOC_DENSITY_THRESHOLD = 2   # 一頁裡「契約」字樣要出現至少這麼多次,才當作是正文而不是目錄


def _norm(text: str) -> str:
    """把 CJK 相容表意文字碼位轉回標準碼位,見上面的說明。"""
    return unicodedata.normalize("NFKC", text)


@dataclass
class LocatedSection:
    pdf_path: str
    pages: list[int]          # 0-indexed 頁碼,方便直接對應 fitz
    text: str
    likely_no_contract: bool  # True 代表原文很可能已經明講「並無簽訂重要契約」


def locate(pdf_path: str) -> LocatedSection | None:
    doc = fitz.open(pdf_path)
    page_texts = [_norm(page.get_text()) for page in doc]

    candidates = [i for i, t in enumerate(page_texts) if SECTION_KEYWORD in t]
    if not candidates:
        return None

    # 在所有出現關鍵字的頁面裡,選「契約」字樣出現次數最多的當錨點,
    # 用來排除目錄頁(目錄頁通常只出現 1 次:章節標題那一行)。
    start = max(candidates, key=lambda i: page_texts[i].count("契約"))

    pages = [start]
    i = start + 1
    while i < len(page_texts) and len(pages) < MAX_CONTINUATION_PAGES:
        t = page_texts[i]
        if any(hint in t for hint in CONTINUATION_HINTS):
            pages.append(i)
            i += 1
        else:
            break

    combined = "\n".join(page_texts[p] for p in pages)
    likely_no_contract = any(p in combined for p in NO_CONTRACT_PATTERNS)

    return LocatedSection(pdf_path=pdf_path, pages=pages, text=combined, likely_no_contract=likely_no_contract)


if __name__ == "__main__":
    import sys
    result = locate(sys.argv[1])
    if result is None:
        print("找不到「重要契約」關鍵字")
    else:
        print(f"頁碼(0-indexed): {result.pages}")
        print(f"疑似無契約聲明: {result.likely_no_contract}")
        print("---")
        print(result.text[:2000])
