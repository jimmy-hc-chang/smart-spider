"""
從實驗室既有的「半導體上市 2025.xlsx」(或未來換成 SQL 資料庫查詢結果)
產生 / 更新 few_shot_examples.json。

目的:隨著資料庫累積更多年份、更多公司的正確答案,可以定期重跑這支
腳本,讓 LLM 抽取時參考的範例愈來愈完整、愈來愈貼近最新的判斷標準
(例如你們決定了新的邊界案例判斷原則,也可以把新案例補進來當範例)。

用法:
    python scripts/build_golden_set.py --xlsx "/path/to/半導體上市 2025.xlsx" --n 15

--n 是想抽幾筆當範例。範例不用多,3-15 筆通常就足夠讓模型抓到風格,
太多反而會拉長每次呼叫的 prompt、增加 API 成本。建議手動挑選涵蓋不同
「合作契約類別」的案例,而不是單純隨機抽樣。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

FIELD_MAP = {
    "乙方代碼": "party_b_code",
    "乙方全稱": "party_b_full_name",
    "乙方簡稱": "party_b_short_name",
    "乙方國": "party_b_country",
    "乙方機構類別": "party_b_org_type",
    "乙方是否在台公發": "party_b_is_tw_listed",
    "合作契約內容": "contract_content",
    "合作契約備註": "contract_note",
    "合作契約類別": "contract_type",
    "合作契約R&D與否": "is_rd_cooperation",
    "是否有合作方向": "direction_code",
    "合作契約起年": "start_year",
    "合作契約訖年": "end_year",
    "是否有終止條件": "has_termination_clause",
    "合作契約終止條件": "termination_clause",
    "是否有保密條款": "has_confidentiality_clause",
    "限制條款": "restriction_clause",
}


def row_to_expected_output(row: pd.Series) -> dict:
    out = {}
    for zh, en in FIELD_MAP.items():
        val = row.get(zh)
        if pd.isna(val):
            val = None
        elif en in ("party_b_code", "party_b_is_tw_listed", "is_rd_cooperation", "direction_code",
                     "start_year", "end_year", "has_termination_clause", "has_confidentiality_clause"):
            val = int(val)
        out[en] = val
    out["confidence"] = "high"
    out["confidence_note"] = None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, help="正式資料庫的 xlsx 匯出檔路徑")
    ap.add_argument("--sheet", default="Sheet1")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "golden_set" / "few_shot_examples.json"))
    args = ap.parse_args()

    df = pd.read_excel(args.xlsx, sheet_name=args.sheet)
    df = df.dropna(subset=["乙方全稱", "合作契約內容"])

    # 盡量涵蓋不同的「合作契約類別」,而不是整批同一種
    sampled = (
        df.groupby("合作契約類別", group_keys=False)
        .apply(lambda g: g.sample(min(len(g), max(1, args.n // df["合作契約類別"].nunique()))))
        .head(args.n)
    )

    examples = []
    for _, row in sampled.iterrows():
        examples.append({
            "source_text": f"(來自既有資料庫,原始 PDF 原文格式請自行對照:公司 {row.get('甲方全稱')})",
            "expected_output": row_to_expected_output(row),
        })

    Path(args.out).write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已寫入 {len(examples)} 筆範例到 {args.out}")
    print("提醒:這些範例的 source_text 沒有真正的 PDF 原文(舊資料庫沒存),")
    print("建議之後手動把幾筆換成真正的 PDF 原文片段,效果會更好(可參考現有 few_shot_examples.json 裡手打的範例)。")


if __name__ == "__main__":
    main()
