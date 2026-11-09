"""
統一讀取金鑰/設定的地方。

同一份程式碼會在三種地方跑:
  1. GitHub Actions(雲端排程)  → 從環境變數讀(GitHub Secrets 會變成環境變數)
  2. Streamlit Cloud(網頁)      → 從 st.secrets 讀(網頁後台的 Secrets 設定)
  3. 實驗室任何一台電腦          → 從 .env 檔讀
這裡把三種來源包成一個 get_secret(),其他程式都只呼叫它。
"""
from __future__ import annotations

import json
import os

from dotenv import load_dotenv

load_dotenv()


def get_secret(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    if val:
        return val
    try:
        import streamlit as st
        if name in st.secrets:
            v = st.secrets[name]
            return v if isinstance(v, str) else json.dumps(dict(v))
    except Exception:  # 不在 Streamlit 裡跑,或沒有 secrets 檔
        pass
    return default


def get_service_account_info() -> dict | None:
    """Google 服務帳號金鑰(JSON)。可以是整段 JSON 字串,也可以是 Streamlit secrets 裡的表格。"""
    raw = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw)
    path = get_secret("GOOGLE_SERVICE_ACCOUNT_FILE")  # 本機用:直接指向下載的 JSON 檔
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None
