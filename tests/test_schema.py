"""基本測試:確保 schema 定義沒有壞掉、欄位數量對得上,
以及範例資料能通過 pydantic 驗證。跑法: pytest tests/ -v"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.schema import COLUMNS, ContractRecord, ExtractionResult


def test_columns_count():
    assert len(COLUMNS) == 23  # 甲方5欄 + 乙方6欄 + 契約12欄,詳見 config/schema.py


def test_contract_record_valid():
    rec = ContractRecord(
        party_b_full_name="測試股份有限公司",
        party_b_short_name="測試",
        party_b_org_type="公司",
        party_b_is_tw_listed=0,
        contract_content="測試合作內容",
        contract_type="授權",
        is_rd_cooperation=1,
        has_confidentiality_clause=0,
        confidence="high",
    )
    assert rec.contract_type == "授權"


def test_contract_record_rejects_bad_org_type_is_just_a_string_not_enforced():
    # 目前 party_b_org_type 是 str 不是 Enum,不會在這裡擋掉不在清單裡的值,
    # 是刻意讓 LLM 的輸出更寬容,由複核介面去挑出不在控制詞彙清單裡的值。
    rec = ContractRecord(
        party_b_full_name="測試",
        party_b_short_name="測試",
        party_b_org_type="不在清單裡的類別",
        party_b_is_tw_listed=0,
        contract_content="x",
        contract_type="授權",
        is_rd_cooperation=1,
        has_confidentiality_clause=0,
        confidence="high",
    )
    assert rec.party_b_org_type == "不在清單裡的類別"


def test_extraction_result_empty_ok():
    result = ExtractionResult(has_any_contract=False, contracts=[])
    assert result.contracts == []
