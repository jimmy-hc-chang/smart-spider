"""
資料存放層。取代原本的 HeidiSQL/MySQL:

- SheetsStore:資料放在 Google 試算表(正式使用)。不用開主機、不會因為
  某台電腦掛掉就登不進去,非資訊背景的人打開試算表就看得懂,也能隨時
  下載成 Excel。
- LocalStore:資料放在本機一個 Excel 檔(data/local_store.xlsx),給
  沒網路時測試、或還沒設定 Google 試算表時先試用。

兩者提供完全一樣的函式,其他程式(一鍵更新、網頁)不需要知道資料實際
放在哪裡。用 get_store() 取得:有設定 SHEET_ID 就用試算表,沒有就用本機檔。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from config.schema import (  # noqa: E402
    COMPANY_COLUMNS, DEFAULT_SETTINGS, DONE_STATUSES, LOG_COLUMNS, MASTER_COLUMNS,
    PENDING_COLUMNS, STATUS_NO_REPORT, TAB_COMPANIES, TAB_LOG, TAB_MASTER, TAB_PENDING,
    TAB_SETTINGS,
)
from src.settings import get_secret, get_service_account_info  # noqa: E402

TAB_COLUMNS = {
    TAB_MASTER: MASTER_COLUMNS,
    TAB_PENDING: PENDING_COLUMNS,
    TAB_COMPANIES: COMPANY_COLUMNS,
    TAB_LOG: LOG_COLUMNS,
    TAB_SETTINGS: ["項目", "值"],
}


def now_str() -> str:
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")  # 台灣時間


def _cell(v):
    """把 None / NaN 轉成空字串,其餘轉成試算表接受的型別。"""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _rows(df: pd.DataFrame, columns: list[str]) -> list[list]:
    df = df.reindex(columns=columns)
    return [[_cell(v) for v in row] for row in df.itertuples(index=False, name=None)]


class BaseStore:
    # ---- 子類別要實作的三個底層動作 ----
    def read(self, tab: str) -> pd.DataFrame: ...
    def append(self, tab: str, df: pd.DataFrame) -> None: ...
    def replace(self, tab: str, df: pd.DataFrame) -> None: ...

    # ---- 共用的高階功能 ----
    def get_companies(self) -> list[str]:
        df = self.read(TAB_COMPANIES)
        codes = [str(c).strip() for c in df.get("股票代碼", []) if str(c).strip()]
        return list(dict.fromkeys(codes))  # 去重、保留順序

    def add_companies(self, codes: list[str], note: str = "") -> int:
        existing = set(self.get_companies())
        new = [c for c in dict.fromkeys(codes) if c and c not in existing]
        if new:
            self.append(TAB_COMPANIES, pd.DataFrame({"股票代碼": new, "備註": note}))
        return len(new)

    def get_settings(self) -> dict:
        df = self.read(TAB_SETTINGS)
        s = dict(DEFAULT_SETTINGS)
        for _, r in df.iterrows():
            if str(r.get("項目", "")).strip():
                s[str(r["項目"]).strip()] = str(r.get("值", "")).strip()
        return s

    def save_settings(self, s: dict) -> None:
        self.replace(TAB_SETTINGS, pd.DataFrame({"項目": list(s.keys()), "值": list(s.values())}))

    def get_log(self) -> pd.DataFrame:
        return self.read(TAB_LOG)

    def log(self, code: str, year: int, status: str, n: int = 0, msg: str = "", how: str = "自動") -> None:
        self.append(TAB_LOG, pd.DataFrame([{
            "股票代碼": code, "年度": year, "狀態": status, "筆數": n,
            "說明": msg, "處理方式": how, "時間": now_str(),
        }]))

    def get_done_keys(self) -> set[tuple[str, int]]:
        """哪些(公司, 年度)已經處理完、不用再跑。
        「抓不到年報」只有在年份夠舊時才算處理完:最近一年的年報可能只是還沒公告,
        之後要再試。"""
        log = self.get_log()
        latest_possible = dt.date.today().year - 1
        done = set()
        for _, r in log.iterrows():
            try:
                key = (str(r["股票代碼"]).strip(), int(float(r["年度"])))
            except (ValueError, TypeError):
                continue
            st = str(r["狀態"])
            if st in DONE_STATUSES or (st == STATUS_NO_REPORT and key[1] < latest_possible):
                done.add(key)
        return done

    def get_pending(self) -> pd.DataFrame:
        return self.read(TAB_PENDING)

    def add_pending(self, rows: list[dict]) -> None:
        if rows:
            self.append(TAB_PENDING, pd.DataFrame(rows))

    def get_master(self) -> pd.DataFrame:
        return self.read(TAB_MASTER)

    def apply_review(self, edited: pd.DataFrame, reviewer: str) -> tuple[int, int]:
        """把網頁上檢查完的結果寫回去。edited 需要有「紀錄ID」與「處理方式」兩欄。
        核准 → 搬進「契約資料」;刪除 → 從「待檢查」移除;其他 → 留在「待檢查」但保存修改。
        為了避免兩個人同時檢查互相覆蓋,寫回前會重新讀一次最新的「待檢查」,
        只更動這次畫面上有出現的那幾筆。"""
        latest = self.get_pending()
        edited = edited.copy()
        edited["紀錄ID"] = edited["紀錄ID"].astype(str)
        action = dict(zip(edited["紀錄ID"], edited["處理方式"]))
        edited_by_id = edited.set_index("紀錄ID")

        approved_rows, keep_rows = [], []
        for _, r in latest.iterrows():
            rid = str(r["紀錄ID"])
            if rid in edited_by_id.index:
                new = edited_by_id.loc[rid]
                merged = {c: (new[c] if c in new.index else r.get(c)) for c in PENDING_COLUMNS if c != "紀錄ID"}
                merged["紀錄ID"] = rid
                act = action.get(rid)
                if act == "核准":
                    approved_rows.append(merged)
                elif act == "刪除":
                    continue
                else:
                    keep_rows.append(merged)
            else:
                keep_rows.append(r.to_dict())

        if approved_rows:
            today = now_str()[:10]
            m = pd.DataFrame(approved_rows)
            m["資料來源"] = "AI抽取+人工檢查"
            m["檢查人"] = reviewer
            m["檢查日期"] = today
            self.append(TAB_MASTER, m)
        self.replace(TAB_PENDING, pd.DataFrame(keep_rows, columns=PENDING_COLUMNS))
        n_deleted = sum(1 for a in action.values() if a == "刪除")
        return len(approved_rows), n_deleted

    def ensure_tabs(self) -> None: ...


class LocalStore(BaseStore):
    def __init__(self, path: Path | None = None):
        self.path = Path(path or REPO_ROOT / "data" / "local_store.xlsx")
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with pd.ExcelWriter(self.path) as w:
                for tab, cols in TAB_COLUMNS.items():
                    pd.DataFrame(columns=cols).to_excel(w, sheet_name=tab, index=False)

    def _all(self) -> dict[str, pd.DataFrame]:
        return pd.read_excel(self.path, sheet_name=None, dtype=str)

    def _write_all(self, sheets: dict[str, pd.DataFrame]) -> None:
        with pd.ExcelWriter(self.path) as w:
            for tab, df in sheets.items():
                df.to_excel(w, sheet_name=tab, index=False)

    def read(self, tab):
        df = self._all().get(tab, pd.DataFrame(columns=TAB_COLUMNS[tab]))
        return df.fillna("").reindex(columns=TAB_COLUMNS[tab], fill_value="")

    def append(self, tab, df):
        sheets = self._all()
        cur = sheets.get(tab, pd.DataFrame(columns=TAB_COLUMNS[tab]))
        add = pd.DataFrame(_rows(df, TAB_COLUMNS[tab]), columns=TAB_COLUMNS[tab]).astype(str)
        sheets[tab] = pd.concat([cur, add], ignore_index=True)
        self._write_all(sheets)

    def replace(self, tab, df):
        sheets = self._all()
        sheets[tab] = pd.DataFrame(_rows(df, TAB_COLUMNS[tab]), columns=TAB_COLUMNS[tab]).astype(str)
        self._write_all(sheets)


class SheetsStore(BaseStore):
    def __init__(self, sheet_id: str, service_account_info: dict):
        import gspread
        self.gc = gspread.service_account_from_dict(service_account_info)
        self.sh = self.gc.open_by_key(sheet_id)
        self.url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"

    def _ws(self, tab):
        import gspread
        try:
            return self.sh.worksheet(tab)
        except gspread.WorksheetNotFound:
            cols = TAB_COLUMNS[tab]
            ws = self.sh.add_worksheet(title=tab, rows=100, cols=max(len(cols), 5))
            ws.update(range_name="A1", values=[cols])
            return ws

    def ensure_tabs(self):
        for tab in TAB_COLUMNS:
            ws = self._ws(tab)
            if not ws.row_values(1):
                ws.update(range_name="A1", values=[TAB_COLUMNS[tab]])

    def read(self, tab):
        values = self._ws(tab).get_all_values()
        if not values:
            return pd.DataFrame(columns=TAB_COLUMNS[tab])
        header, body = values[0], values[1:]
        width = len(header)
        body = [row + [""] * (width - len(row)) for row in body]
        df = pd.DataFrame(body, columns=header)
        return df.reindex(columns=TAB_COLUMNS[tab], fill_value="")

    def append(self, tab, df, chunk=500):
        ws = self._ws(tab)
        rows = _rows(df, TAB_COLUMNS[tab])
        for i in range(0, len(rows), chunk):
            ws.append_rows(rows[i:i + chunk], value_input_option="RAW")

    def replace(self, tab, df):
        ws = self._ws(tab)
        cols = TAB_COLUMNS[tab]
        data = [cols] + _rows(df, cols)
        ws.clear()
        ws.resize(rows=max(len(data) + 20, 50), cols=max(len(cols), 5))
        ws.update(range_name="A1", values=data, value_input_option="RAW")


def get_store() -> BaseStore:
    sheet_id = get_secret("SHEET_ID")
    info = get_service_account_info()
    if sheet_id and info:
        return SheetsStore(sheet_id, info)
    return LocalStore()
