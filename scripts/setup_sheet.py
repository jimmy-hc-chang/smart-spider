"""
一次性設定:建立 Google 試算表的五個分頁,並把舊資料搬進去。只有第一次
建置時由管理者跑一次,之後不用再跑。

    python scripts/setup_sheet.py --history "半導體上市 2025.xlsx"

會做三件事:
  1. 建立「契約資料/待檢查/公司清單/處理紀錄/設定」五個分頁(已存在就略過)
  2. 把舊 Excel 的 4,000 多筆歷史資料搬進「契約資料」,資料來源標成「人工整理(舊資料庫)」
  3. 把舊資料裡出現過的公司加進「公司清單」(config/companies.csv 也一併加入)
  已經搬過一次再跑,會偵測到「契約資料」已有舊資料而跳過第 2 步,不會重複。

沒設定 SHEET_ID 時,會改寫進本機 data/local_store.xlsx,方便先試用。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from config.schema import COLUMNS, DEFAULT_SETTINGS, TAB_MASTER  # noqa: E402
from src.storage.store import get_store  # noqa: E402

HISTORY_TAG = "人工整理(舊資料庫)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", help="舊資料庫匯出的 Excel,例如「半導體上市 2025.xlsx」")
    ap.add_argument("--sheet", default="Sheet1")
    args = ap.parse_args()

    store = get_store()
    print("儲存位置:", getattr(store, "url", None) or getattr(store, "path", None))
    store.ensure_tabs()

    if not store.read("設定").shape[0]:
        store.save_settings(DEFAULT_SETTINGS)
        print("已建立預設設定:", DEFAULT_SETTINGS)

    codes = []
    if args.history:
        df = pd.read_excel(args.history, sheet_name=args.sheet)
        df = df[[c for c in COLUMNS if c in df.columns]].copy()
        df = df.dropna(how="all")
        master = store.get_master()
        if (master.get("資料來源", pd.Series(dtype=str)) == HISTORY_TAG).any():
            print("「契約資料」裡已經有舊資料,略過搬遷(避免重複)")
        else:
            df["資料來源"] = HISTORY_TAG
            store.append(TAB_MASTER, df)
            print(f"已搬入 {len(df)} 筆歷史資料")
        codes += [str(int(c)) for c in df["甲方代碼"].dropna()]

    csv_path = REPO_ROOT / "config" / "companies.csv"
    if csv_path.exists():
        with open(csv_path, encoding="utf-8-sig") as f:
            codes += [r["stock_code"].strip() for r in csv.DictReader(f) if r["stock_code"].strip()]
    n = store.add_companies(codes, note="初始名單")
    print(f"公司清單新增 {n} 家,共 {len(store.get_companies())} 家")
    print("完成。")


if __name__ == "__main__":
    main()
