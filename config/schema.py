"""
單一資料來源:契約資料的 25 欄位 schema + 控制詞彙。

抓取、抽取、複核介面、入庫,四個模組都 import 這個檔案,
確保欄位名稱、順序、允許值永遠一致。
以後如果要調整欄位,只需要改這裡一個地方。

控制詞彙(合作契約類別 / 乙方機構類別 的允許值)是從實驗室既有的
「半導體上市 2025.xlsx」4,438 筆歷史資料統計出來的高頻值,新出現的
值不代表錯誤,只是 LLM 沒看過這個詞,遇到新詞會在複核介面特別標記,
請人工確認後把新詞加進這個清單。
"""
from pydantic import BaseModel, Field
from typing import Optional

# 資料庫 / Excel 的正式欄位,順序即輸出順序
COLUMNS = [
    "甲方代碼", "甲方全稱", "甲方簡稱", "甲方機構類別", "甲方是否在台公發",
    "乙方代碼", "乙方全稱", "乙方簡稱", "乙方國", "乙方機構類別", "乙方是否在台公發",
    "合作契約內容", "合作契約備註", "合作契約類別", "合作契約R&D與否", "是否有合作方向",
    "合作契約起年", "合作契約訖年", "是否有終止條件", "合作契約終止條件",
    "合作契約所屬年報年份", "是否有保密條款", "限制條款",
]

# 複核用的額外欄位(不寫入正式資料庫,只在複核階段使用)
REVIEW_ONLY_COLUMNS = ["來源PDF", "來源頁碼", "AI信心", "AI信心說明", "複核狀態", "複核人", "複核備註"]

ALL_COLUMNS = COLUMNS + REVIEW_ONLY_COLUMNS

# 從歷史資料統計出的控制詞彙,詳見 scripts/build_controlled_vocab.py
CONTRACT_TYPE_VALUES = [
    "授權", "委託製造", "合作開發", "移轉", "產學合作",
    "合作研究", "委託研究", "技術開發", "技術合作", "技術授權",
]
PARTY_B_TYPE_VALUES = ["公司", "研究機構(財團法人)", "大學、中研院", "大學", "政府機關", "機構"]

# 「是否有合作方向」代碼,依歷史資料反推,尚未經實驗室正式確認(見 README「待確認事項」)
DIRECTION_CODE_MEANING = {
    1: "甲方授權/移轉技術給乙方 (甲→乙)",
    2: "乙方授權/移轉技術給甲方 (乙→甲)",
    3: "共同合作,方向不明確偏向雙方共同投入",
    4: "交互授權 / 雙向",
}


class ContractRecord(BaseModel):
    """LLM 結構化輸出用的 schema。欄位名用英文避免 Gemini structured output 對中文
    key 的相容性問題,寫檔時再用 FIELD_NAME_MAP 轉成中文欄名。"""

    party_b_code: Optional[int] = Field(None, description="乙方股票代碼,只有乙方也是台灣上市櫃公司時才會有")
    party_b_full_name: str = Field(..., description="乙方全稱,原文照抄")
    party_b_short_name: str = Field(..., description="乙方簡稱,若原文沒有簡稱就用全稱")
    party_b_country: Optional[str] = Field(None, description="乙方所屬國家,原文沒寫就填 null,不要用猜的")
    party_b_org_type: str = Field(..., description=f"乙方機構類別,必須是以下其中一個: {PARTY_B_TYPE_VALUES}")
    party_b_is_tw_listed: int = Field(..., description="乙方是否為台灣公開發行公司,是=1否=0")

    contract_content: str = Field(..., description="合作契約主要內容,盡量保留原文用字")
    contract_note: Optional[str] = None
    contract_type: str = Field(..., description=f"合作契約類別,必須是以下其中一個: {CONTRACT_TYPE_VALUES}")
    is_rd_cooperation: int = Field(..., description="是否屬於研發合作/技術授權/專利授權/產學合作等(1),還是租賃/一般採購/工程發包/供應合約等應排除的契約(0)")

    direction_code: Optional[int] = Field(None, description=f"合作方向代碼,對照: {DIRECTION_CODE_MEANING},無法判斷就填 null")
    start_year: Optional[int] = Field(None, description="契約起年,西元年,原文是民國年要換算(民國年+1911)")
    end_year: Optional[int] = Field(None, description="契約訖年,西元年;若原文寫「起」或無到期日,填 9999")
    has_termination_clause: Optional[int] = Field(None, description="是否有明確的提前終止條件,是=1否=0,原文沒提就填 null")
    termination_clause: Optional[str] = None

    has_confidentiality_clause: int = Field(..., description="限制條款文字中是否包含保密/機密義務,是=1否=0")
    restriction_clause: Optional[str] = Field(None, description="限制條款原文,若原文寫「無」就填「無」")

    confidence: str = Field(..., description="high / medium / low —— 任何欄位是用推測而非原文明載填入時,信心不能是 high")
    confidence_note: Optional[str] = Field(None, description="信心不是 high 時,說明是哪個欄位、為什麼不確定")


class ExtractionResult(BaseModel):
    """一頁/一段「重要契約」文字,經 LLM 判讀後的完整輸出。"""
    has_any_contract: bool = Field(..., description="這段重要契約原文是否明確聲明「並無簽訂重要契約」等,若是則為 false")
    contracts: list[ContractRecord] = Field(default_factory=list)


# ===================== 雲端版(Google 試算表)用的分頁與欄位 =====================
# 試算表裡固定會有這五個分頁,setup_sheet.py 會自動建立。
TAB_MASTER = "契約資料"      # 正式資料庫(歷史資料 + 人工檢查通過的新資料)
TAB_PENDING = "待檢查"       # AI 抽取完、還沒有人檢查的資料
TAB_COMPANIES = "公司清單"   # 要追蹤的公司,一行一個股票代碼
TAB_LOG = "處理紀錄"         # 每一份年報處理過沒有、結果如何
TAB_SETTINGS = "設定"        # 起始年份、每次處理份數等

MASTER_EXTRA_COLUMNS = ["資料來源", "檢查人", "檢查日期", "來源連結", "來源頁碼"]
MASTER_COLUMNS = COLUMNS + MASTER_EXTRA_COLUMNS

PENDING_COLUMNS = ["紀錄ID"] + COLUMNS + ["來源連結", "來源頁碼", "AI信心", "AI信心說明", "建立時間"]

COMPANY_COLUMNS = ["股票代碼", "備註"]

LOG_COLUMNS = ["股票代碼", "年度", "狀態", "筆數", "說明", "處理方式", "時間"]

# 處理紀錄裡的「狀態」。DONE 代表這份年報不用再處理。
STATUS_OK = "成功"
STATUS_NO_CONTRACT = "無重要契約"
STATUS_NO_RD = "無研發合作契約"
STATUS_NOT_FOUND_SECTION = "找不到重要契約章節(可能是掃描檔,需人工)"
STATUS_NO_REPORT = "抓不到年報"
STATUS_ERROR = "錯誤"
DONE_STATUSES = {STATUS_OK, STATUS_NO_CONTRACT, STATUS_NO_RD, STATUS_NOT_FOUND_SECTION}

DEFAULT_SETTINGS = {
    "起始年份": "2024",          # 歷史資料已涵蓋 1998-2023;想重新回補可改成 1998
    "每次最多處理份數": "20",    # Gemini 免費額度每天有上限,設太大會中途用完(用完會自動明天繼續)
    "Gemini模型": "gemini-flash-latest",
}
