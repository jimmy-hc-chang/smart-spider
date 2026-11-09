"""
「一鍵更新」實際執行的工作。平常由 GitHub Actions 在雲端跑(每天自動一次,
或在網頁上按「一鍵更新」觸發),不需要任何一台實驗室電腦開著。

流程:
  1. 從試算表讀「公司清單」「設定」「處理紀錄」
  2. 算出還沒處理過的(公司, 年度),最新年度優先
  3. 每一份:下載年報 → 找重要契約 → Gemini 抽取 → 寫進「待檢查」→ 記到「處理紀錄」
  4. 一次最多處理「每次最多處理份數」份;Gemini 免費額度用完就停,明天自動接著做

也可以在任何一台裝好環境的電腦手動跑(結果一樣寫進同一份試算表):
    python -m src.cloud.run_update
    python -m src.cloud.run_update --max-items 5
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from config.schema import STATUS_ERROR, STATUS_NO_REPORT  # noqa: E402
from src.extract.analyze import analyze_pdf  # noqa: E402
from src.scraper.download_annual_reports import download_one, source_link  # noqa: E402
from src.storage.store import get_store  # noqa: E402


def plan(companies: list[str], done: set, start_year: int, end_year: int) -> list[tuple[str, int]]:
    """最新年度優先:每年更新時,今年該抓的會先被處理,再慢慢往回補舊年份。"""
    return [(c, y) for y in range(end_year, start_year - 1, -1) for c in companies if (c, y) not in done]


def run(max_items: int | None = None, store=None, downloader=download_one, extractor=None,
        sleep_between: float = 2.0) -> dict:
    store = store or get_store()
    settings = store.get_settings()
    if settings.get("Gemini模型"):
        os.environ.setdefault("GEMINI_MODEL", settings["Gemini模型"])

    start_year = int(settings.get("起始年份") or 2024)
    end_year = dt.date.today().year - 1  # 年報隔年才公告
    limit = max_items or int(settings.get("每次最多處理份數") or 20)

    companies = store.get_companies()
    todo = plan(companies, store.get_done_keys(), start_year, end_year)
    batch = todo[:limit]
    print(f"公司 {len(companies)} 家,年度 {start_year}-{end_year},尚未處理 {len(todo)} 份,這次處理 {len(batch)} 份")

    from src.extract.llm_extract import QuotaExceeded

    stats = {"處理": 0, "新增待檢查": 0, "抓不到": 0, "錯誤": 0, "剩餘": len(todo), "額度用完": False}
    session = requests.Session()
    for i, (code, year) in enumerate(batch, 1):
        print(f"({i}/{len(batch)}) {code} {year}")
        with tempfile.TemporaryDirectory() as tmp:
            try:
                pdf = downloader(session, code, year, out_dir=Path(tmp))
            except Exception as e:  # noqa: BLE001
                pdf = None
                print("   下載錯誤:", e)
            if not pdf:
                store.log(code, year, STATUS_NO_REPORT, 0, "公開資訊觀測站抓不到(可能當年未上市或尚未公告)")
                stats["抓不到"] += 1
                stats["處理"] += 1
                continue
            try:
                status, rows, msg = analyze_pdf(pdf, code, year, source_link=source_link(code, year),
                                                extractor=extractor)
            except QuotaExceeded:
                print("   Gemini 今日免費額度用完,停止;下次執行會從這裡接著做。")
                stats["額度用完"] = True
                break
            except Exception as e:  # noqa: BLE001
                store.log(code, year, STATUS_ERROR, 0, str(e)[:300])
                stats["錯誤"] += 1
                stats["處理"] += 1
                continue
        store.add_pending(rows)
        store.log(code, year, status, len(rows), msg)
        stats["處理"] += 1
        stats["新增待檢查"] += len(rows)
        print(f"   {status}:{msg}")
        time.sleep(sleep_between)

    stats["剩餘"] = len(todo) - stats["處理"]
    summary = (f"處理 {stats['處理']} 份、新增待檢查 {stats['新增待檢查']} 筆、抓不到 {stats['抓不到']} 份、"
               f"錯誤 {stats['錯誤']} 份、還剩 {stats['剩餘']} 份未處理"
               + (";Gemini 額度用完,明天自動繼續" if stats["額度用完"] else ""))
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"### 本次更新結果\n\n{summary}\n")
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-items", type=int, default=None)
    args = ap.parse_args()
    env_max = os.environ.get("MAX_ITEMS", "").strip()
    run(max_items=args.max_items or (int(env_max) if env_max.isdigit() else None))


if __name__ == "__main__":
    main()
