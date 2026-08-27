"""
呼叫 Gemini API,把「重要契約」段落的原文轉成結構化資料。

用的是 Google 的 google-genai SDK,重點是 response_schema 這個參數:
Gemini 會被強制只能回傳符合 config/schema.py 裡 ExtractionResult 格式
的 JSON,不會有「模型多講廢話、還要自己 regex 解析」的問題。

【為什麼要放歷史資料當 few-shot】
實驗室已經累積了十幾年、上千筆人工標註過的正確答案(半導體上市
2025.xlsx)。與其讓模型憑空理解「什麼叫研發合作」「限制條款要抓多細」
不如直接把幾個真實案例做成範例放進 prompt,模型的輸出風格會自動貼齊
既有資料庫的寫法(例如年份用西元、無到期日用 9999、限制條款原文照抄)。
few-shot 範例放在 data/golden_set/few_shot_examples.json,
scripts/build_golden_set.py 說明如何從你們的正式資料庫重新產生/更新
這份範例。

這支程式只依賴 GEMINI_API_KEY 這個環境變數,跟任何互動式 AI 對話介面
無關 —— 是你們自己申請的 API 金鑰、自己控制用量與帳單,拔掉這次對話
也完全不影響這支程式運作。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.schema import ExtractionResult, CONTRACT_TYPE_VALUES, PARTY_B_TYPE_VALUES, DIRECTION_CODE_MEANING

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
FEW_SHOT_PATH = REPO_ROOT / "data" / "golden_set" / "few_shot_examples.json"

SYSTEM_PROMPT = f"""你是台灣上市櫃公司年報「重要契約」章節的資訊擷取助理,任務是把
一段年報原文,轉成結構化的契約清單,供實驗室建立研發合作關係資料庫。

規則:
1. 只擷取跟「研發合作」有關的契約:技術授權、專利授權/交互授權、合作開發、
   產學合作、合作研究、技術移轉等。租賃契約、一般原物料/晶圓材料採購
   (進貨)、工程發包、財務性合約(如借款、保證)一律不要輸出,is_rd_cooperation
   也不會是這些類別。
2. 每一筆契約都要對應到原文裡的一個獨立段落/表格列,不要合併也不要拆分原文
   已經寫在一起的內容。
3. 「乙方」是跟這家公司(甲方)簽約的對方,可能是公司、大學、研究機構、政府
   機關。乙方機構類別只能是: {PARTY_B_TYPE_VALUES}
4. 合作契約類別只能是: {CONTRACT_TYPE_VALUES} 。如果原文用詞不在這個清單裡
   (例如契約性質欄位寫了一個沒看過的詞),選最接近的既有類別,並在
   confidence_note 註明原文用詞,不要自己發明新類別。
5. 日期一律轉西元年(民國年+1911)。原文寫「起」、沒有到期日的,end_year 填 9999。
6. 任何欄位原文沒有明講、需要用推測才能填的(尤其是乙方國籍、合作方向代碼),
   confidence 不能填 high,並在 confidence_note 說明。不要為了填滿欄位而編造
   看起來合理但原文沒有根據的內容。
7. 如果原文明確聲明「並無簽訂重要契約」等,has_any_contract 填 false,
   contracts 留空陣列,不要硬找。
8. 合作方向代碼定義(僅供參考,不確定就填 null): {DIRECTION_CODE_MEANING}
"""


def _load_few_shot_block() -> str:
    if not FEW_SHOT_PATH.exists():
        return ""
    examples = json.loads(FEW_SHOT_PATH.read_text(encoding="utf-8"))
    if not examples:
        return ""
    block = "\n\n以下是實驗室既有資料庫裡,人工確認過的正確範例,輸出風格請對齊這些範例:\n"
    for ex in examples:
        block += f"\n原文片段:\n{ex['source_text']}\n對應的正確輸出:\n{json.dumps(ex['expected_output'], ensure_ascii=False)}\n"
    return block


def extract(section_text: str, *, model: str | None = None) -> ExtractionResult:
    """把定位到的「重要契約」段落文字丟給 Gemini,回傳結構化結果。"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("找不到 GEMINI_API_KEY,請先複製 .env.example 為 .env 並填入金鑰")

    model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)

    prompt = SYSTEM_PROMPT + _load_few_shot_block() + f"\n\n請處理以下原文:\n\n{section_text}"

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractionResult,
        ),
    )

    # google-genai 在 response_schema 是 pydantic model 時,response.parsed 就是
    # 一個現成的 ExtractionResult 物件;保留手動解析當作備援,避免 SDK 版本差異。
    if getattr(response, "parsed", None) is not None:
        return response.parsed
    return ExtractionResult.model_validate_json(response.text)


if __name__ == "__main__":
    import sys as _sys
    text = Path(_sys.argv[1]).read_text(encoding="utf-8")
    result = extract(text)
    print(result.model_dump_json(indent=2, exclude_none=True))
