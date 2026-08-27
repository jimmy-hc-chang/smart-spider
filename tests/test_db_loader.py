"""測試 DB loader 在沒有設定 DATABASE_URL 時,能正確 fallback 到本機 SQLite,
且寫入的資料讀得回來、欄位數對得上。"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.schema import COLUMNS
from src.db.load_to_db import get_engine, load_dataframe, TABLE_NAME


def test_load_and_read_back(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    row = {c: None for c in COLUMNS}
    row.update({"甲方代碼": "2303", "甲方全稱": "測試公司", "乙方全稱": "測試乙方", "合作契約類別": "授權"})
    df = pd.DataFrame([row])

    n = load_dataframe(df)
    assert n == 1

    engine = get_engine()
    back = pd.read_sql_table(TABLE_NAME, engine)
    assert len(back) == 1
    assert back.iloc[0]["甲方全稱"] == "測試公司"
