"""
工讀生用的複核介面。取代「打開 PDF 逐字謄寫進 Excel」,改成「看 AI 已經
填好的表格,對照原文頁碼快速核對、修正低信心欄位」。

啟動方式(在 repo 根目錄下):
    streamlit run src/review_app/app.py

流程:
1. 選擇 data/extracted/ 底下要複核的 CSV(run_pipeline.py 產生的)。
2. 表格由上而下複核,AI信心=low 的欄位會特別標示,建議優先看這些。
   「來源PDF」「來源頁碼」告訴你要對照 data/raw_pdfs/ 裡哪一份 PDF 的
   哪幾頁,不用整本重讀。
3. 直接在表格裡修正儲存格內容(跟 Excel 一樣點兩下編輯)。
4. 每一列選複核狀態:已核准 / 已修正 / 刪除(不算研發合作,AI 誤判)。
5. 按下方按鈕,把「已核准」+「已修正」的列匯出成正式格式的 Excel,
   或直接寫入資料庫(需要先在 .env 設定 DATABASE_URL)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from config.schema import COLUMNS  # noqa: E402

EXTRACTED_DIR = REPO_ROOT / "data" / "extracted"
RAW_PDF_DIR = REPO_ROOT / "data" / "raw_pdfs"

st.set_page_config(page_title="重要契約複核", layout="wide")
st.title("重要契約抽取複核")

csv_files = sorted(EXTRACTED_DIR.glob("*.csv"))
if not csv_files:
    st.warning(f"{EXTRACTED_DIR} 底下沒有待複核的 CSV,請先執行 run_pipeline.py 產生抽取結果。")
    st.stop()

chosen = st.selectbox("選擇要複核的檔案", csv_files, format_func=lambda p: p.name)
# utf-8-sig:CSV 存檔時統一加 UTF-8 BOM 方便用 Excel 直接開,讀取要對應用 utf-8-sig
df = pd.read_csv(chosen, dtype=str, encoding="utf-8-sig").fillna("")

low_conf_count = (df["AI信心"] == "low").sum()
medium_conf_count = (df["AI信心"] == "medium").sum()
st.info(f"共 {len(df)} 筆待複核。信心度 低:{low_conf_count} 筆、中:{medium_conf_count} 筆 —— 建議優先看這些。")

st.caption("提示:點兩下儲存格可以直接編輯;「複核狀態」欄位請選擇 已核准 / 已修正 / 刪除。"
           "「來源PDF」「來源頁碼」對照 data/raw_pdfs/ 底下的原始 PDF 確認原文。")

edited = st.data_editor(
    df,
    num_rows="dynamic",
    use_container_width=True,
    height=600,
    column_config={
        "複核狀態": st.column_config.SelectboxColumn(options=["待複核", "已核准", "已修正", "刪除"]),
        "AI信心": st.column_config.TextColumn(disabled=True),
        "來源PDF": st.column_config.TextColumn(disabled=True),
        "來源頁碼": st.column_config.TextColumn(disabled=True),
    },
    key="editor",
)

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("儲存複核進度(存回同一個 CSV)", type="secondary"):
        edited.to_csv(chosen, index=False, encoding="utf-8-sig")
        st.success("已儲存複核進度")

with col2:
    if st.button("匯出「已核准/已修正」為正式 Excel", type="primary"):
        approved = edited[edited["複核狀態"].isin(["已核准", "已修正"])]
        out_path = EXTRACTED_DIR / f"{chosen.stem}_已核准.xlsx"
        approved[COLUMNS].to_excel(out_path, index=False)
        st.success(f"已匯出 {len(approved)} 筆到 {out_path}")

with col3:
    if st.button("寫入資料庫"):
        approved = edited[edited["複核狀態"].isin(["已核准", "已修正"])]
        if approved.empty:
            st.warning("沒有已核准/已修正的資料可以寫入")
        else:
            try:
                sys.path.insert(0, str(REPO_ROOT))
                from src.db.load_to_db import load_dataframe
                n = load_dataframe(approved[COLUMNS])
                st.success(f"已寫入資料庫,共 {n} 筆")
            except Exception as e:  # noqa: BLE001
                st.error(f"寫入失敗: {e}")

st.divider()
st.caption(
    "「是否有合作方向」代碼對照:1=甲方授權/移轉給乙方、2=乙方授權/移轉給甲方、"
    "3=方向不明的共同合作、4=交互授權(雙向)。這組代碼是從歷史資料反推的,"
    "如果跟實驗室原本的定義不同,請告知並更新 config/schema.py。"
)
