"""
把複核通過的資料寫入 SQL 資料庫。

目前不確定實驗室資料庫實際是哪一種(MySQL / PostgreSQL / 其他),
所以這支程式用 SQLAlchemy 寫成「連線字串換一行就好」的通用版本:

    - 沒設定 DATABASE_URL 時,預設寫入本機 data/contracts.db(SQLite),
      不需要另外架設資料庫伺服器,適合先跑起來看資料對不對。
    - 確認資料庫種類後,在 .env 設定 DATABASE_URL,例如:
        MySQL:      mysql+pymysql://user:password@host:3306/dbname
        PostgreSQL: postgresql+psycopg2://user:password@host:5432/dbname
      並且要多安裝對應的 driver 套件(pymysql 或 psycopg2-binary),
      requirements.txt 裡沒有預先裝,因為不確定會用到哪一種。

資料表名稱、欄位都直接對應 config/schema.py 的 COLUMNS,25 欄。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from config.schema import COLUMNS  # noqa: E402

TABLE_NAME = "rd_contracts"
DEFAULT_SQLITE_PATH = REPO_ROOT / "data" / "contracts.db"


def get_engine():
    url = os.environ.get("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_PATH}"
    return create_engine(url)


def load_dataframe(df: pd.DataFrame) -> int:
    """寫入資料庫,回傳寫入筆數。用 append 模式,不會覆蓋既有資料;
    如果需要去重(同一份契約每年報都出現一次的情況你們是刻意保留歷史軌跡,
    詳見架構建議文件),去重邏輯留給你們依實際需求決定,這裡故意不自動刪。"""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"缺少欄位: {missing}")

    engine = get_engine()
    df[COLUMNS].to_sql(TABLE_NAME, engine, if_exists="append", index=False)
    return len(df)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="把一份已核准的 Excel/CSV 寫入資料庫")
    ap.add_argument("file", help="已核准的 .xlsx 或 .csv 檔案路徑")
    args = ap.parse_args()

    df = pd.read_excel(args.file) if args.file.endswith(".xlsx") else pd.read_csv(args.file)
    n = load_dataframe(df)
    print(f"已寫入 {n} 筆到資料表 {TABLE_NAME}(連線: {os.environ.get('DATABASE_URL', 'sqlite (預設)')})")
