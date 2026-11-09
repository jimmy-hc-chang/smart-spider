"""
背景下載公開資訊觀測站(MOPS)年報 PDF,取代舊版 F04.ipynb 的
Selenium + pyautogui 做法。

【跟舊版最大的差異】
舊版之所以要開一個看得見的 Chrome 視窗、用 pyautogui 模擬滑鼠鍵盤做
「右鍵→另存新檔」,單純是因為程式邏輯用瀏覽器的下載功能來存檔,
而不是因為那個 PDF 資源本身需要瀏覽器才能拿到。這支程式改成直接對
同一個網址發 HTTP 請求、把回應內容(bytes)寫進檔案 —— 效果一樣,
但完全背景執行,不會佔用你的滑鼠鍵盤,可以排程跑、可以同時做別的事。

【流程,對應舊版程式碼】
1. GET  https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&co_id={股票代碼}&year={民國年}&mtype=F&
   → 這頁會列出該公司當年度所有年報相關文件的連結,舊版用
     `find_element_by_partial_link_text('F04')` 找「F04」那個連結。
2. 舊版接著切換到新開的分頁,在裡面找到一個 <a> 標籤(通常就是實際
   PDF 檔案的連結或下載按鈕),對它按右鍵存檔。
   這支程式改成直接 GET 那個 <a> 的 href,把回應內容存成 PDF。

【重要:這段還沒有機會用真實網路連線驗證】
我沒辦法從目前的環境連線到 doc.twse.com.tw 做即時測試,所以下面的
`step1`/`step2` 是照舊版程式碼的操作邏輯重建的「最佳推測」,不保證
網站的實際 HTML 結構完全吻合。第一次用之前,請照下面的方式驗證:

    python -m src.scraper.download_annual_reports --debug --stock 2303 --year 112

加上 --debug 會把每一步抓到的 HTML 存到 data/raw_pdfs/_debug/,
方便你打開來看跟預期的結構(F04 連結、下載連結)是否一致。如果抓到
的內容跟預期不同,通常代表:
  (a) 該頁面其實需要先建立 session/cookie(用 requests.Session() 應該
      仍能處理,cookie 會自動保留在 session 物件裡),或
  (b) 該頁面內容是 JavaScript 動態產生的,GET 到的原始 HTML 沒有連結
      → 這種情況才需要退回用 Playwright headless 模式render完再抓
      (headless 一樣不會有看得見的視窗、不會佔用電腦)。
      可以參考 download_annual_reports_playwright.py.example。
"""
from __future__ import annotations

import argparse
import csv
import datetime
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://doc.twse.com.tw/server-java/t57sb01"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw_pdfs"
DEBUG_DIR = RAW_DIR / "_debug"


def roc_year(western_year: int) -> int:
    """西元年轉民國年,例如 2023 -> 112。網站的 year 參數吃民國年。"""
    return western_year - 1911


def step1_find_f04_link(session: requests.Session, stock_code: str, roc: int, debug: bool) -> str | None:
    """對應舊版 driver.get(...) + find_element_by_partial_link_text('F04')。
    回傳 F04 文件連結的完整網址,找不到回傳 None。"""
    url = f"{BASE}?step=1&colorchg=1&co_id={stock_code}&year={roc}&mtype=F&"
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.encoding = resp.apparent_encoding or "big5"

    if debug:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"{stock_code}_{roc}_step1.html").write_text(resp.text, encoding="utf-8", errors="replace")

    soup = BeautifulSoup(resp.text, "html.parser")
    # 找連結文字包含 F04 的 <a>,邏輯對應舊版的 partial_link_text
    for a in soup.find_all("a"):
        if a.get_text() and "F04" in a.get_text():
            href = a.get("href")
            if not href:
                continue
            if href.startswith("http"):
                return href
            # 相對路徑要補成完整網址
            return requests.compat.urljoin(url, href)
    return None


def step2_find_pdf_link(session: requests.Session, page_url: str, stock_code: str, roc: int, debug: bool) -> str | None:
    """對應舊版切到新分頁後 find_element_by_tag_name('a') 抓到的那個連結。
    有些情況下 step1 找到的網址可能『就是』 PDF 本身(Content-Type 直接是
    application/pdf),這種情況這一步會直接把同一個網址原樣送回去,由
    download() 判斷 Content-Type 決定要不要再往下一層找。"""
    resp = session.get(page_url, headers=HEADERS, timeout=20)
    content_type = resp.headers.get("Content-Type", "")
    if "pdf" in content_type.lower():
        return page_url

    resp.encoding = resp.apparent_encoding or "big5"
    if debug:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"{stock_code}_{roc}_step2.html").write_text(resp.text, encoding="utf-8", errors="replace")

    soup = BeautifulSoup(resp.text, "html.parser")
    a = soup.find("a")
    if a and a.get("href"):
        href = a["href"]
        return href if href.startswith("http") else requests.compat.urljoin(page_url, href)
    return None


def source_link(stock_code: str, western_year: int) -> str:
    """該公司該年度在公開資訊觀測站的文件清單網址。網址是固定的,
    存在資料裡,檢查的人點一下就能回去看原始年報。"""
    return f"{BASE}?step=1&colorchg=1&co_id={stock_code}&year={roc_year(western_year)}&mtype=F&"


def download_one(session: requests.Session, stock_code: str, western_year: int, debug: bool = False,
                 out_dir: Path | None = None) -> Path | None:
    roc = roc_year(western_year)
    out_dir = Path(out_dir) if out_dir else RAW_DIR
    out_path = out_dir / f"{stock_code}_{western_year}.pdf"
    if out_path.exists():
        print(f"[skip] {out_path.name} 已存在")
        return out_path

    f04_url = step1_find_f04_link(session, stock_code, roc, debug)
    if not f04_url:
        print(f"[fail] {stock_code} {western_year}(民國{roc}年):第一步就沒找到 F04 連結,"
              f"該公司這一年可能沒有公告年報,或網頁結構跟預期不同,建議加 --debug 檢查")
        return None

    pdf_url = step2_find_pdf_link(session, f04_url, stock_code, roc, debug)
    if not pdf_url:
        print(f"[fail] {stock_code} {western_year}:找到 F04 連結但第二步沒找到 PDF,建議加 --debug 檢查")
        return None

    resp = session.get(pdf_url, headers=HEADERS, timeout=60)
    if "pdf" not in resp.headers.get("Content-Type", "").lower() and not resp.content[:4] == b"%PDF":
        print(f"[fail] {stock_code} {western_year}:下載到的內容不是 PDF(Content-Type="
              f"{resp.headers.get('Content-Type')}),建議加 --debug 檢查")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)
    print(f"[ok] 存成 {out_path}")
    return out_path


def load_companies(csv_path: Path) -> list[str]:
    # utf-8-sig:companies.csv 存的時候有加 UTF-8 BOM(方便 Excel 直接開不會亂碼),
    # 讀取時要用 utf-8-sig 才能正確跳過 BOM,不然第一個欄位名稱會變成 "\ufeffstock_code"
    with open(csv_path, encoding="utf-8-sig") as f:
        return [row["stock_code"] for row in csv.DictReader(f)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stock", help="單一股票代碼,不指定就跑 config/companies.csv 全部公司")
    ap.add_argument("--year", type=int, help="只抓單一西元年,例如 2023(代表民國112年年報)")
    ap.add_argument("--start-year", type=int, default=1998,
                     help="歷史回補起始西元年(預設 1998,公開資訊觀測站最早的電子化年報年份)")
    ap.add_argument("--end-year", type=int, default=None,
                     help="歷史回補結束西元年(預設去年,因為年報隔年才公告)。跟 --year 擇一使用,同時給的話 --year 優先")
    ap.add_argument("--companies-csv", default=str(REPO_ROOT / "config" / "companies.csv"))
    ap.add_argument("--sleep", type=float, default=1.5, help="每次下載間隔秒數,避免對政府網站造成負擔")
    ap.add_argument("--debug", action="store_true", help="把中間過程的 HTML 存下來方便除錯")
    args = ap.parse_args()

    stocks = [args.stock] if args.stock else load_companies(Path(args.companies_csv))

    if args.year:
        years = [args.year]
    else:
        # 年報是隔年才公告(例如 2025 年度的年報 2026 年 5-6 月才出),所以預設抓到「去年」
        end_year = args.end_year or datetime.date.today().year - 1
        years = list(range(args.start_year, end_year + 1))

    total = len(stocks) * len(years)
    print(f"預計處理 {len(stocks)} 家公司 x {len(years)} 個年份({years[0]}-{years[-1]}) = 最多 {total} 份 PDF")
    print("注意:公司在某些年份可能還沒上市/沒有公告年報,這些會顯示 [fail] 並直接跳過,是正常現象,"
          "不是每一份都抓得到,回補到 1998 的情況尤其常見(公司上市前不會有任何年報)。")

    session = requests.Session()
    ok, fail = 0, 0
    n = 0
    for code in stocks:
        for year in years:
            n += 1
            print(f"({n}/{total}) {code} {year} ...")
            result = download_one(session, code, year, debug=args.debug)
            ok += 1 if result else 0
            fail += 0 if result else 1
            time.sleep(args.sleep)

    print(f"\n完成。成功 {ok},失敗 {fail}。PDF 存在 {RAW_DIR}")
    print("失敗有兩種可能:(a) 該公司那一年還沒上市/沒有年報,正常現象,不用管;"
          "(b) 網站結構跟預期不同抓不到,這種情況建議針對某一筆已知「應該要抓得到」的"
          "公司+年份加 --debug --stock --year 重跑,檢查 data/raw_pdfs/_debug/ 下的 HTML。")


if __name__ == "__main__":
    sys.exit(main())
