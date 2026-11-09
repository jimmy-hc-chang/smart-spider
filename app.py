"""
重要契約研發合作資料庫 —— 給所有人用的網頁。

部署在 Streamlit Community Cloud(免費),大家只要打開網址、輸入實驗室
密碼就能用,不用裝任何東西、不用懂程式。本機試跑:streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import io
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from config.schema import (  # noqa: E402
    COLUMNS, CONTRACT_TYPE_VALUES, DEFAULT_SETTINGS, PARTY_B_TYPE_VALUES, TAB_COMPANIES,
)
from src.settings import get_secret  # noqa: E402
from src.storage.store import LocalStore, get_store  # noqa: E402

st.set_page_config(page_title="重要契約研發合作資料庫", layout="wide")


# ---------------- 密碼 ----------------
def password_gate():
    pw = get_secret("APP_PASSWORD")
    if not pw or st.session_state.get("authed"):
        return
    st.title("重要契約研發合作資料庫")
    x = st.text_input("請輸入實驗室密碼", type="password")
    if x and x == pw:
        st.session_state["authed"] = True
        st.rerun()
    elif x:
        st.error("密碼錯誤")
    st.stop()


password_gate()


@st.cache_resource
def store():
    return get_store()


S = store()
using_local = isinstance(S, LocalStore)

st.title("重要契約研發合作資料庫")
if using_local:
    st.warning("目前是「本機試用模式」:資料存在這台電腦的 data/local_store.xlsx。"
               "正式使用請管理者依「管理者設定手冊」接上 Google 試算表。")

tab_home, tab_review, tab_upload, tab_companies, tab_download, tab_help = st.tabs(
    ["首頁:一鍵更新", "檢查 AI 結果", "手動上傳年報", "公司清單與設定", "下載 Excel", "使用說明"])


# ---------------- 首頁 ----------------
with tab_home:
    from src.cloud import github_trigger as gh

    settings = S.get_settings()
    companies = S.get_companies()
    log = S.get_log()
    pending = S.get_pending()
    master = S.get_master()

    start_y = int(settings.get("起始年份") or 2024)
    end_y = dt.date.today().year - 1
    total = len(companies) * max(0, end_y - start_y + 1)
    done = len([k for k in S.get_done_keys() if start_y <= k[1] <= end_y and k[0] in set(companies)])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("追蹤公司", f"{len(companies)} 家")
    c2.metric("年報處理進度", f"{done} / {total}", help=f"{start_y}–{end_y} 年度")
    c3.metric("等待檢查", f"{len(pending)} 筆")
    c4.metric("資料庫總筆數", f"{len(master)} 筆")
    if total:
        st.progress(min(done / total, 1.0))

    st.subheader("一鍵更新")
    st.write("按下去之後,雲端會自動:下載還沒處理的年報 → 找出重要契約 → AI 判讀研發合作 → "
             "放進「檢查 AI 結果」等你確認。**不用開著電腦,可以直接關掉這個網頁。** "
             "系統每天凌晨也會自動跑一次。")
    if gh.configured():
        running = gh.is_running()
        if running:
            st.info("目前正在更新中,完成後結果會出現在「檢查 AI 結果」。")
        with st.expander("進階:這次要處理幾份"):
            n_items = st.number_input("最多處理幾份年報(0 = 用設定裡的數字)", 0, 500, 0)
        if st.button("一鍵更新", type="primary", disabled=running):
            ok, msg = gh.trigger(n_items or None)
            (st.success if ok else st.error)(msg + ("。大約 10–30 分鐘,可以先去做別的事。" if ok else ""))
        try:
            runs = gh.recent_runs(5)
            if runs:
                st.caption("最近幾次執行")
                st.dataframe(pd.DataFrame(runs), hide_index=True, width="stretch",
                             column_config={"詳細": st.column_config.LinkColumn(display_text="查看")})
        except Exception as e:  # noqa: BLE001
            st.caption(f"(讀不到執行紀錄:{e})")
    else:
        st.info("一鍵更新按鈕還沒設定(管理者需要在 Streamlit Secrets 填 GITHUB_APP_TOKEN 與 GITHUB_REPO)。"
                "在那之前,可以用「手動上傳年報」分頁。")

    st.subheader("最近處理紀錄")
    if len(log):
        st.dataframe(log.iloc[::-1].head(30), hide_index=True, width="stretch")
    else:
        st.caption("還沒有任何紀錄")


# ---------------- 檢查 AI 結果 ----------------
with tab_review:
    st.write("AI 抽取的結果會先放在這裡,**檢查過按「核准」才會進入正式資料庫**。"
             "「AI信心」是低/中的優先看;點「來源連結」可以打開原始年報對照(頁碼在「來源頁碼」)。"
             "表格可以直接點兩下修改內容。")
    if st.button("重新整理", key="refresh_review"):
        st.rerun()
    pend = S.get_pending()
    if pend.empty:
        st.success("目前沒有等待檢查的資料。")
    else:
        f1, f2 = st.columns(2)
        comps = sorted(pend["甲方代碼"].astype(str).unique())
        pick = f1.multiselect("只看這些公司(不選 = 全部)", comps)
        only_unsure = f2.checkbox("只看 AI 沒把握的(信心 低/中)")
        view = pend.copy()
        if pick:
            view = view[view["甲方代碼"].astype(str).isin(pick)]
        if only_unsure:
            view = view[view["AI信心"].isin(["low", "medium", "低", "中"])]
        order = {"low": 0, "medium": 1, "high": 2}
        view = view.assign(_o=view["AI信心"].map(order).fillna(1)).sort_values("_o").drop(columns="_o")
        view.insert(0, "處理方式", "待檢查")

        show_cols = ["處理方式", "AI信心", "甲方代碼", "甲方全稱", "合作契約所屬年報年份", "乙方全稱",
                     "乙方簡稱", "乙方國", "乙方機構類別", "合作契約內容", "合作契約類別", "是否有合作方向",
                     "合作契約起年", "合作契約訖年", "限制條款", "是否有保密條款", "AI信心說明",
                     "來源連結", "來源頁碼"]
        rest = [c for c in view.columns if c not in show_cols]
        edited = st.data_editor(
            view[show_cols + rest], hide_index=True, width="stretch", height=520,
            key="review_editor",
            column_config={
                "處理方式": st.column_config.SelectboxColumn(options=["待檢查", "核准", "刪除"], required=True,
                                                         help="核准=進正式資料庫;刪除=AI 判斷錯誤,不是研發合作"),
                "合作契約類別": st.column_config.SelectboxColumn(options=CONTRACT_TYPE_VALUES),
                "乙方機構類別": st.column_config.SelectboxColumn(options=PARTY_B_TYPE_VALUES),
                "來源連結": st.column_config.LinkColumn(display_text="打開年報"),
                "AI信心": st.column_config.TextColumn(disabled=True),
                "紀錄ID": st.column_config.TextColumn(disabled=True),
            })
        b1, b2 = st.columns([3, 1])
        reviewer = b1.text_input("檢查人姓名(必填)")
        if b2.button("送出檢查結果", type="primary"):
            if not reviewer.strip():
                st.error("請先填檢查人姓名")
            elif (edited["處理方式"] == "待檢查").all():
                st.warning("還沒有任何一筆選「核准」或「刪除」")
            else:
                n_ok, n_del = S.apply_review(edited, reviewer.strip())
                st.success(f"完成:{n_ok} 筆進入正式資料庫,{n_del} 筆刪除。")
                st.rerun()


# ---------------- 手動上傳 ----------------
with tab_upload:
    st.write("萬一自動下載抓不到某份年報,或想補特定公司,可以把 PDF 直接拖進來。"
             "檔名如果是「股票代碼_年度.pdf」(例如 2303_2024.pdf)會自動帶入,否則請手動填。")
    files = st.file_uploader("拖曳年報 PDF 到這裡(可多份)", type=["pdf"], accept_multiple_files=True)
    jobs = []
    for i, f in enumerate(files or []):
        m = re.match(r"^(\d{4,6})_(\d{4})", f.name)
        a, b = st.columns(2)
        code = a.text_input(f"{f.name}:股票代碼", value=m.group(1) if m else "", key=f"code{i}")
        year = b.number_input(f"{f.name}:年報年度(西元,例如 2024 年度年報填 2024)", 1990, 2100,
                              int(m.group(2)) if m else dt.date.today().year - 1, key=f"year{i}")
        jobs.append((f, code.strip(), int(year)))
    if jobs and st.button("開始分析", type="primary"):
        from src.extract.analyze import analyze_pdf
        from src.scraper.download_annual_reports import source_link
        for f, code, year in jobs:
            if not code:
                st.error(f"{f.name}:請填股票代碼")
                continue
            with st.spinner(f"分析 {f.name} 中(約 10–60 秒)…"):
                with tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp) / f"{code}_{year}.pdf"
                    p.write_bytes(f.getvalue())
                    try:
                        status, rows, msg = analyze_pdf(p, code, year, source_link=source_link(code, year))
                    except Exception as e:  # noqa: BLE001
                        st.error(f"{f.name}:分析失敗({e})")
                        continue
            S.add_pending(rows)
            S.log(code, year, status, len(rows), msg, how="手動上傳")
            st.success(f"{f.name}:{status},{msg}" + ("。請到「檢查 AI 結果」確認。" if rows else ""))
        S.add_companies([c for _, c, _ in jobs if c], note="手動上傳時加入")


# ---------------- 公司清單與設定 ----------------
with tab_companies:
    st.subheader("要追蹤的公司")
    st.write("從 TEJ 匯出目標領域的公司後,把「股票代碼」那一欄整欄複製,貼到下面的框框就好。")
    pasted = st.text_area("貼上股票代碼(一行一個,或用空白/逗號分隔都可以)", height=120)
    note = st.text_input("這批公司的備註(例如:TEJ 半導體業 2026)")
    if st.button("加入公司清單"):
        codes = re.findall(r"\d{4,6}", pasted)
        n = S.add_companies(codes, note=note)
        st.success(f"新增 {n} 家(重複的會自動略過)")
        st.rerun()
    comp_df = S.read(TAB_COMPANIES)
    edited_comp = st.data_editor(comp_df, num_rows="dynamic", hide_index=True, width="stretch",
                                 key="comp_editor")
    if st.button("儲存公司清單(含刪除)"):
        S.replace(TAB_COMPANIES, edited_comp)
        st.success("已儲存")

    st.subheader("設定")
    s = S.get_settings()
    y = st.number_input("從哪一年開始處理", 1998, 2100, int(s.get("起始年份") or 2024),
                        help="舊資料庫已整理到 2023 年度,預設從 2024 開始。改成 1998 會用 AI 重新跑所有舊年份。")
    n = st.number_input("每次最多處理幾份年報", 1, 500, int(s.get("每次最多處理份數") or 20),
                        help="Gemini 免費額度每天有限,設太大會中途用完(用完會自動隔天繼續,不會壞掉)。")
    model = st.text_input("Gemini 模型", s.get("Gemini模型") or DEFAULT_SETTINGS["Gemini模型"],
                          help="一般不用改。gemini-flash-latest 會自動用最新的 Flash 模型。")
    if st.button("儲存設定"):
        S.save_settings({"起始年份": str(y), "每次最多處理份數": str(n), "Gemini模型": model})
        st.success("已儲存")


# ---------------- 下載 ----------------
with tab_download:
    def to_xlsx(df: pd.DataFrame) -> bytes:
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        return buf.getvalue()

    m = S.get_master()
    st.write(f"正式資料庫共 {len(m)} 筆。")
    yrs = sorted({v for v in m["合作契約所屬年報年份"].astype(str) if v})
    pick_y = st.multiselect("只下載這些年度(不選 = 全部)", yrs)
    out = m[m["合作契約所屬年報年份"].astype(str).isin(pick_y)] if pick_y else m
    st.download_button("下載正式資料庫 Excel", to_xlsx(out), "重要契約研發合作資料庫.xlsx", type="primary")
    st.download_button("下載「只有原本 23 欄」版本(跟舊資料庫格式一樣)", to_xlsx(out[COLUMNS]),
                       "重要契約研發合作資料庫_23欄.xlsx")
    st.download_button("下載等待檢查的資料", to_xlsx(S.get_pending()), "待檢查.xlsx")
    if getattr(S, "url", None):
        st.link_button("直接打開 Google 試算表", S.url)


# ---------------- 說明 ----------------
with tab_help:
    p = REPO_ROOT / "docs" / "使用手冊.md"
    st.markdown(p.read_text(encoding="utf-8") if p.exists() else "請見 docs/使用手冊.md")
