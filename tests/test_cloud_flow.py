"""雲端版流程測試:用本機儲存 + 假下載 + 假 AI,不需要網路或金鑰。"""
import sys
from pathlib import Path

import fitz
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.schema import ContractRecord, ExtractionResult  # noqa: E402
from src.cloud.run_update import run  # noqa: E402
from src.storage.store import LocalStore  # noqa: E402


def make_pdf(path: Path, body: str):
    doc = fitz.open()
    for text in ["測試電子股份有限公司 年報", body]:
        page = doc.new_page()
        page.insert_text((50, 72), text, fontname="china-t", fontsize=11)
    doc.save(path)


def fake_extract(text):
    return ExtractionResult(has_any_contract=True, contracts=[
        ContractRecord(party_b_full_name="某大學", party_b_short_name="某大學", party_b_org_type="大學",
                       party_b_is_tw_listed=0, contract_content="產學合作", contract_type="產學合作",
                       is_rd_cooperation=1, has_confidentiality_clause=0, confidence="high"),
        ContractRecord(party_b_full_name="某房東", party_b_short_name="房東", party_b_org_type="公司",
                       party_b_is_tw_listed=0, contract_content="廠房租賃", contract_type="授權",
                       is_rd_cooperation=0, has_confidentiality_clause=0, confidence="high"),
    ])


def test_full_flow(tmp_path):
    S = LocalStore(tmp_path / "store.xlsx")
    S.add_companies(["1111", "2222"])
    import datetime
    Y = datetime.date.today().year - 1   # 最新可能有年報的年度
    S.save_settings({"起始年份": str(Y - 1), "每次最多處理份數": "10", "Gemini模型": "x"})

    def fake_download(session, code, year, out_dir):
        if code != "1111" or year != Y:
            return None
        p = Path(out_dir) / f"{code}_{year}.pdf"
        make_pdf(p, "重要契約 契約性質 契約對象 限制條款 產學合作")
        return p

    stats = run(store=S, downloader=fake_download, extractor=fake_extract, sleep_between=0, max_items=4)
    assert stats["新增待檢查"] == 1           # 租賃那筆被擋掉
    pend = S.get_pending()
    assert pend.iloc[0]["甲方全稱"] == "測試電子股份有限公司"  # 從封面猜到公司名
    done = S.get_done_keys()
    assert ("1111", Y) in done                 # 成功的算處理完
    assert ("2222", Y - 1) in done             # 舊年份抓不到也算處理完
    assert ("2222", Y) not in done             # 最新年度抓不到:可能還沒公告,之後要再試

    ed = pend.copy()
    ed["處理方式"] = "核准"
    ok, deleted = S.apply_review(ed, "測試")
    assert (ok, deleted) == (1, 0)
    assert len(S.get_pending()) == 0
    assert S.get_master().iloc[-1]["檢查人"] == "測試"


def test_paste_companies_dedup(tmp_path):
    S = LocalStore(tmp_path / "s.xlsx")
    assert S.add_companies(["2330", "2330", "2303"]) == 2
    assert S.add_companies(["2330", "2454"]) == 1
    assert S.get_companies() == ["2330", "2303", "2454"]
