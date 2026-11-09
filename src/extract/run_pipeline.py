"""
整條抽取流程的入口:給一個 PDF(或一個資料夾的多個 PDF),
定位「重要契約」段落 → 丟給 Gemini 結構化抽取 → 輸出一份「待複核」的
CSV,欄位包含 config/schema.py 定義的正式 25 欄,外加來源頁碼與 AI
信心註記,方便工讀生用 review_app 複核。

用法:
    # 處理單一 PDF
    python -m src.extract.run_pipeline --pdf data/raw_pdfs/2303_2023.pdf \
        --stock 2303 --company-name 聯華電子股份有限公司 --company-short 聯華 \
        --report-year 2023

    # 處理整個資料夾(檔名要是「股票代碼_西元年.pdf」,跟 scraper 存檔慣例一致)
    python -m src.extract.run_pipeline --dir data/raw_pdfs --companies-csv config/companies.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import unicodedata

import fitz  # pymupdf

from config.schema import COLUMNS, REVIEW_ONLY_COLUMNS  # noqa: E402
from src.extract.locate_contracts import locate  # noqa: E402
from src.extract.llm_extract import extract  # noqa: E402

from src.extract.analyze import guess_company_name  # noqa: E402,F401

FIELD_MAP_EN_TO_ZH = {
    "party_b_code": "乙方代碼", "party_b_full_name": "乙方全稱", "party_b_short_name": "乙方簡稱",
    "party_b_country": "乙方國", "party_b_org_type": "乙方機構類別", "party_b_is_tw_listed": "乙方是否在台公發",
    "contract_content": "合作契約內容", "contract_note": "合作契約備註", "contract_type": "合作契約類別",
    "is_rd_cooperation": "合作契約R&D與否", "direction_code": "是否有合作方向",
    "start_year": "合作契約起年", "end_year": "合作契約訖年",
    "has_termination_clause": "是否有終止條件", "termination_clause": "合作契約終止條件",
    "has_confidentiality_clause": "是否有保密條款", "restriction_clause": "限制條款",
}


def process_one_pdf(pdf_path: Path, stock_code: str, company_name: str | None, company_short: str | None,
                     report_year: int) -> list[dict]:
    if not company_name:
        company_name = guess_company_name(pdf_path)
        if company_name:
            print(f"  [提示] {pdf_path.name}:companies.csv 沒填公司全名,從封面頁猜到「{company_name}」,"
                  f"建議複核時順便確認一下")
        else:
            company_name = f"(未知,股票代碼{stock_code})"
            print(f"  [警告] {pdf_path.name}:companies.csv 沒填公司全名,封面頁也猜不到,"
                  f"請人工補上甲方全稱")
    if not company_short:
        company_short = company_name

    section = locate(str(pdf_path))
    if section is None:
        print(f"  [警告] {pdf_path.name}:找不到「重要契約」段落,請人工確認是否為特殊排版(可能需要 OCR)")
        return []

    if section.likely_no_contract:
        print(f"  [ok] {pdf_path.name}:原文疑似聲明無重要契約,略過 LLM 呼叫(頁碼 {section.pages})")
        return []

    result = extract(section.text)
    if not result.has_any_contract or not result.contracts:
        print(f"  [ok] {pdf_path.name}:LLM 判斷無研發合作相關契約(頁碼 {section.pages})")
        return []

    rows = []
    for c in result.contracts:
        row = {
            "甲方代碼": stock_code, "甲方全稱": company_name, "甲方簡稱": company_short,
            "甲方機構類別": "公司", "甲方是否在台公發": 1,
            "合作契約所屬年報年份": report_year,
        }
        for en, zh in FIELD_MAP_EN_TO_ZH.items():
            row[zh] = getattr(c, en)
        row["來源PDF"] = pdf_path.name
        row["來源頁碼"] = ",".join(str(p + 1) for p in section.pages)  # 轉成人類看的 1-indexed 頁碼
        row["AI信心"] = c.confidence
        row["AI信心說明"] = c.confidence_note
        row["複核狀態"] = "待複核"
        row["複核人"] = ""
        row["複核備註"] = ""
        rows.append(row)

    print(f"  [ok] {pdf_path.name}:抽取出 {len(rows)} 筆研發合作相關契約")
    return rows


def load_companies(csv_path: Path) -> dict[str, tuple[str | None, str | None]]:
    # utf-8-sig:見 scraper/download_annual_reports.py 裡同名函式的註解
    # full_name / short_name 是選填欄位:只有 stock_code 這一欄是必要的,
    # 沒填名字的公司會在 process_one_pdf() 用 guess_company_name() 從 PDF 封面頁補。
    with open(csv_path, encoding="utf-8-sig") as f:
        result = {}
        for r in csv.DictReader(f):
            code = r["stock_code"].strip()
            full = (r.get("full_name") or "").strip() or None
            short = (r.get("short_name") or "").strip() or None
            result[code] = (full, short)
        return result


FILENAME_RE = re.compile(r"^(\d+)_(\d{4})\.pdf$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", help="單一 PDF 路徑")
    ap.add_argument("--dir", help="批次處理整個資料夾")
    ap.add_argument("--stock", help="--pdf 模式:股票代碼")
    ap.add_argument("--company-name", help="--pdf 模式:公司全名")
    ap.add_argument("--company-short", help="--pdf 模式:公司簡稱")
    ap.add_argument("--report-year", type=int, help="--pdf 模式:年報所屬西元年")
    ap.add_argument("--companies-csv", default=str(REPO_ROOT / "config" / "companies.csv"))
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "extracted" / "待複核.csv"))
    args = ap.parse_args()

    all_rows: list[dict] = []

    if args.pdf:
        all_rows += process_one_pdf(Path(args.pdf), args.stock, args.company_name,
                                     args.company_short, args.report_year)
    elif args.dir:
        companies = load_companies(Path(args.companies_csv))
        pdfs = sorted(Path(args.dir).glob("*.pdf"))
        print(f"找到 {len(pdfs)} 份 PDF")
        for pdf_path in pdfs:
            m = FILENAME_RE.match(pdf_path.name)
            if not m:
                print(f"  [跳過] {pdf_path.name}:檔名不是「股票代碼_西元年.pdf」格式")
                continue
            stock, year = m.group(1), int(m.group(2))
            if stock not in companies:
                print(f"  [跳過] {pdf_path.name}:{stock} 不在 {args.companies_csv} 名單裡")
                continue
            name, short = companies[stock]
            all_rows += process_one_pdf(pdf_path, stock, name, short, year)
    else:
        ap.error("要指定 --pdf 或 --dir 其中一個")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = COLUMNS + REVIEW_ONLY_COLUMNS
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n共 {len(all_rows)} 筆待複核記錄,已存到 {out_path}")
    print("下一步:執行 `streamlit run src/review_app/app.py` 打開複核介面")


if __name__ == "__main__":
    main()
