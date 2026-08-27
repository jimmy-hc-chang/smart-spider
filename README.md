# 重要契約研發合作抽取管線

用 LLM 自動從公開發行公司年報的「重要契約」段落,抽取研發合作/技術授權
關係,取代「爬蟲霸占電腦手動下載 + 工讀生逐字謄寫進 Excel」的舊流程。

這份 README 假設接手的人是新進的工讀生或研究生,不一定寫過 Python,
請照順序做,卡住的地方多半是下面「常見問題」有寫。

## 這套系統在做什麼(先看這個,再動手裝東西)

```
① 抓取PDF          ② 定位「重要契約」段落      ③ LLM結構化抽取         ④ 人工複核 → 入庫
(背景執行,          (從整本200-300頁的年報,     (套用25欄schema、        (Streamlit網頁,
不會佔用電腦)        自動找出契約表格所在頁)      過濾非研發合作契約)      工讀生審核/修正)
```

- **不需要**一直開著 Claude 或任何 AI 對話視窗。這裡的「LLM」是指程式
  碼裡呼叫 Google Gemini API(`src/extract/llm_extract.py`),用的是
  自己申請的 API 金鑰,跟任何聊天介面沒有關係 —— 概念上就跟呼叫
  Google 翻譯 API 或任何雲端服務一樣,是程式的一個依賴套件,不是要有人
  在旁邊跟 AI 對話。
- 需要人工的地方只剩最後一步「複核」,而且介面會標出 AI 沒把握的欄位,
  不用整份重讀。

## 第一次安裝

```bash
python -m venv .venv
source .venv/bin/activate        # Windows 用 .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

打開 `.env`,填入:
1. `GEMINI_API_KEY` —— 去 https://aistudio.google.com/apikey 用自己的
   Google 帳號申請,有免費額度。**這組金鑰是自己的資產**,
   交接時要注意,不要留在只有一個人知道的地方。
2. `DATABASE_URL` —— 如果還不確定實驗室資料庫是哪一種,先留空,系統
   會自動用本機的 SQLite 檔案(`data/contracts.db`),不影響前面抓取跟
   抽取的流程,之後確定資料庫種類再回來填這一行就好(見下方「入庫」)。

## 平常怎麼用(一年一次的年報更新流程)

```bash
# 1a. 抓取單一年份:把 config/companies.csv 裡所有公司的指定年度年報 PDF 抓下來
python -m src.scraper.download_annual_reports --year 2025

# 1b. 歷史回補:對每家公司,從 1998 抓到今年所有年份(第一次建置資料庫時用這個)
python -m src.scraper.download_annual_reports --start-year 1998
# 只想回補某一家公司:python -m src.scraper.download_annual_reports --stock 2303 --start-year 1998
# 已經抓過的檔案會自動跳過(看 data/raw_pdfs/ 裡有沒有同名檔案),重跑很安全,
# 抓不到的年份(通常是那家公司那一年還沒上市)會顯示 [fail] 直接跳過,是正常現象。

# 2. 抽取:定位「重要契約」段落 + 呼叫 Gemini 結構化抽取
python -m src.extract.run_pipeline --dir data/raw_pdfs --companies-csv config/companies.csv

# 3. 複核:打開網頁介面,人工審核 AI 抽取結果
streamlit run src/review_app/app.py
```

也可以用 `make download YEAR=2025`、`make download-all-history`、`make extract`、`make review` 執行同樣的事。

複核介面裡把每一列標成「已核准」或「已修正」之後,按「匯出正式 Excel」
或「寫入資料庫」即可,細節見複核介面上的操作提示。

## 各資料夾放什麼

- `config/companies.csv`:目前追蹤的公司名單(股票代碼、全名、簡稱)。
  這份是從你們既有的「半導體上市 2025.xlsx」反推出來的 82 家公司起始
  清單,增減公司直接編輯這個 CSV 就好。**還沒接上 TEJ 產業分類**——目前
  版本需要你們手動維護這份清單,TEJ 匯出檔的匯入腳本待補(見下方
  「已知限制」)。
- `config/schema.py`:**全系統唯一的欄位定義來源**。抓取、抽取、複核、
  入庫四個模組都從這裡讀欄位名稱與控制詞彙,要調整欄位只改這一個地方。
- `data/raw_pdfs/`:下載下來的年報 PDF,檔名格式固定是
  `股票代碼_西元年.pdf`,抽取流程靠這個檔名規則知道要填哪個公司哪個年度。
- `data/extracted/`:每次跑抽取產生的「待複核」CSV,以及複核後匯出的
  正式 Excel。
- `data/golden_set/`:給 LLM 參考的正確範例(few-shot),見下方說明。

## 準確率怎麼維持:golden set / few-shot 範例

`data/golden_set/few_shot_examples.json` 裡放的是幾筆人工確認過的正確
答案,每次呼叫 Gemini 都會把這些範例一起放進 prompt,讓輸出風格貼齊你們
既有資料庫的寫法。這份清單建議:

- 每隔一段時間(例如每年抽取完成後),從新複核過的資料裡挑幾筆有代表性
  的案例(尤其是之前 AI 判斷錯誤、後來人工修正過的案例)補進去。
- 用 `python scripts/build_golden_set.py --xlsx "半導體上市 2025.xlsx"`
  可以從既有資料庫批次產生範例草稿,但這樣產生的範例沒有真正的 PDF 原文
  片段(舊資料庫沒存),效果不如手動挑選、附上原文的範例,建議两種方式
  搭配使用。

## 入庫:接到你們真正的 SQL 資料庫

`src/db/load_to_db.py` 用 SQLAlchemy 寫,換資料庫只要改 `.env` 的
`DATABASE_URL` 一行,不用改程式碼:

```
MySQL:      DATABASE_URL=mysql+pymysql://user:password@host:3306/dbname
PostgreSQL: DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname
```

用哪一種資料庫要多裝對應的 driver(`pip install pymysql` 或
`pip install psycopg2-binary`),因為不確定實際會接哪一種,requirements.txt
裡沒有預先裝。資料表名稱是 `rd_contracts`,欄位對應 `config/schema.py`。

**去重提醒**:你們既有資料庫的慣例是同一份契約,只要還在有效期內,
「每一年的年報」都會重複出現一筆(用「合作契約所屬年報年份」區分),
這是刻意保留的歷史軌跡,`load_to_db.py` 預設不會自動刪重複,去重邏輯
(如果需要的話)請依你們實際的分析需求再決定怎麼做。

## 測試

```bash
python -m pytest tests/ -v
```

`test_schema.py`、`test_db_loader.py` 不需要任何外部連線,裝好套件就能跑。
`test_locate_contracts.py` 需要一份真實的年報 PDF 才會執行:

```bash
PDF_FOR_TEST=data/raw_pdfs/2303_2025.pdf python -m pytest tests/test_locate_contracts.py -v
```

## 已知限制 / 待確認事項

0. **TEJ 產業分類還沒串接。** 目前 `config/companies.csv` 是手動維護的
   固定清單,不會依照 TEJ 的產業分類自動選公司。原因很單純:TEJ 是需要
   帳號登入的付費資料庫,我這邊沒有你們的 TEJ 帳號或 API 金鑰,沒辦法
   自己連進去抓,而且就算有帳號,直接寫程式登入網頁/桌面版去爬資料通常
   也違反 TEJ 的使用條款,不建議這樣做。可行的兩條路:
   (a) 如果實驗室有訂閱 **TEJ API / TQuant**(程式化查詢的付費方案,
   不是網頁版或桌面版),把 API 文件或一個範例回應格式給我,我可以寫一支
   `scripts/import_from_tej_api.py` 定期用你們自己的 API 金鑰查詢最新分類,
   全自動、不需要手動匯出。
   (b) 如果沒有 API、只有網頁版/TEJ+ 桌面版可以手動匯出 Excel/CSV,那就是
   「每年手動匯出一次(通常幾分鐘)+ 程式自動讀取轉換」,匯出的頻率遠低於
   現在逐份年報人工判讀的頻率,仍然是很大的省力。把匯出檔案傳給我(或告訴
   我欄位長相),我可以寫 `scripts/import_from_tej_export.py` 把它轉成
   `config/companies.csv` 的格式。

1. **抓取腳本(`src/scraper/`)還沒機會用真實網路連線驗證過。** 我是照
   舊版 F04.ipynb 的操作邏輯(t57sb01 頁面 → 找 F04 連結 → 找 PDF 連結)
   重寫成 HTTP 請求版本,但沒辦法從我的環境連線到 doc.twse.com.tw 實際
   測試。**第一次使用前,請先用 `--debug --stock 2303 --year 2025` 跑
   一家公司驗證**,細節見 `download_annual_reports.py` 檔案開頭的說明。
   如果抓不到,大機率是該網站的內容需要 JavaScript 才能產生,這時候
   改用 Playwright headless 模式(一樣不會佔用電腦,見程式裡的說明)。

2. **「是否有合作方向」欄位的 1/2/3/4 代碼定義**,是我從你們既有資料
   反推出來的猜測(見 `config/schema.py` 的 `DIRECTION_CODE_MEANING`),
   不是官方定義,麻煩實驗室確認正確定義後更新這個檔案。

3. **中文字型的相容碼位問題**:實測發現有些公司的 PDF(尤其是舊版
   Word 匯出的)中文字用的是 Unicode「CJK 相容表意文字」碼位,肉眼看
   起來一樣,但字串比對比不中,已經在 `locate_contracts.py` 用
   `unicodedata.normalize('NFKC', ...)` 處理過,如果之後遇到其他關鍵字
   (例如比對公司名稱)也比對不到的情況,先檢查是不是同樣的原因。

4. **少數年報可能是掃描圖檔**(尤其是較舊的年報),沒有可選取文字,
   `locate_contracts.py` 會直接回傳「找不到重要契約」,需要另外接 OCR
   (例如 `pytesseract` 或雲端 OCR API)才能處理,這部分還沒有實作,
   量不大的話用人工判讀處理這少數幾份可能比較划算。

## 為什麼不做成一個要架設伺服器的網站

抓取、抽取、入庫都是命令列腳本,複核用 Streamlit(單一 Python 檔案就是
整個網頁,不用另外寫前端),這樣的好處是實驗室不用養一台常駐伺服器、
不用處理登入權限這些額外的維運成本,新進的人只要會跑 `python` 指令、
`streamlit run` 就能用,交接成本低。如果之後真的需要多人同時協作複核、
留修改紀錄,再考慮把 Streamlit 換成正式部署的網站,現在這個規模不需要。
