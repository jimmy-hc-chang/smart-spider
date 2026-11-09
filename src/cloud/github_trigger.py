"""網頁上的「一鍵更新」按鈕:呼叫 GitHub API 啟動雲端工作,並查詢最近幾次執行狀態。

需要的設定(放在 Streamlit Secrets):
  GITHUB_APP_TOKEN  一組只有這個 repo「Actions 讀寫」權限的 fine-grained token
  GITHUB_REPO       例如 tiger-lab-png/smart-spider
  GITHUB_BRANCH     預設 main
"""
from __future__ import annotations

import requests

from src.settings import get_secret

WORKFLOW_FILE = "update.yml"
STATUS_ZH = {"queued": "排隊中", "in_progress": "執行中", "completed": "已完成", "waiting": "等待中"}
CONCLUSION_ZH = {"success": "成功", "failure": "失敗", "cancelled": "已取消", "timed_out": "逾時", None: ""}


def configured() -> bool:
    return bool(get_secret("GITHUB_APP_TOKEN") and get_secret("GITHUB_REPO"))


def _headers():
    return {"Authorization": f"Bearer {get_secret('GITHUB_APP_TOKEN')}",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _base():
    return f"https://api.github.com/repos/{get_secret('GITHUB_REPO')}/actions/workflows/{WORKFLOW_FILE}"


def trigger(max_items: int | None = None) -> tuple[bool, str]:
    r = requests.post(f"{_base()}/dispatches", headers=_headers(), timeout=20,
                      json={"ref": get_secret("GITHUB_BRANCH", "main"),
                            "inputs": {"max_items": str(max_items or "")}})
    if r.status_code == 204:
        return True, "已開始更新"
    return False, f"GitHub 回應 {r.status_code}:{r.text[:200]}"


def recent_runs(n: int = 5) -> list[dict]:
    r = requests.get(f"{_base()}/runs", headers=_headers(), params={"per_page": n}, timeout=20)
    r.raise_for_status()
    out = []
    for run in r.json().get("workflow_runs", []):
        out.append({
            "開始時間": run["created_at"].replace("T", " ").replace("Z", " UTC"),
            "觸發方式": "手動一鍵" if run["event"] == "workflow_dispatch" else "每日自動",
            "狀態": STATUS_ZH.get(run["status"], run["status"]),
            "結果": CONCLUSION_ZH.get(run.get("conclusion"), run.get("conclusion") or ""),
            "詳細": run["html_url"],
        })
    return out


def is_running() -> bool:
    try:
        return any(r["狀態"] in ("排隊中", "執行中", "等待中") for r in recent_runs(3))
    except Exception:  # noqa: BLE001
        return False
