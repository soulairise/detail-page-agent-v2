"""실행 상태 저장소. state.json이 단일 진실 원본, trace.jsonl은 append-only 로그."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
KST = timezone(timedelta(hours=9))

_lock = threading.RLock()

STAGES = [
    "입력·넓은 조사",
    "포지셔닝 선택",
    "심층 조사·편집 판단",
    "스토리보드 승인",
    "카피·컴플라이언스",
    "조립·이미지 계획",
    "검수·내보내기",
]


def now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def run_dir(run_id: str) -> Path:
    return RUNS / run_id


def state_path(run_id: str) -> Path:
    return run_dir(run_id) / "state.json"


def artifacts_dir(run_id: str) -> Path:
    return run_dir(run_id) / "artifacts"


def create_run(run_id: str, product: dict, profile: str) -> dict:
    with _lock:
        artifacts_dir(run_id).mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "product": product,
            "profile": profile,
            "stage": 1,
            "stage_note": "",
            "status": "idle",
            "session_id": None,
            "pending_question": None,
            "pending_approval": None,
            "answers": [],
            "artifacts": [],
            "compliance": None,
            "usage": {
                "turns": 0,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "elapsed_s": 0,
            },
            "halt_reason": None,
            "created_at": now(),
            "updated_at": now(),
        }
        save(state)
        return state


def load(run_id: str) -> dict | None:
    p = state_path(run_id)
    if not p.exists():
        return None
    with _lock:
        return json.loads(p.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    with _lock:
        state["updated_at"] = now()
        p = state_path(state["run_id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(p)


def update(run_id: str, **fields: Any) -> dict:
    with _lock:
        state = load(run_id)
        if state is None:
            raise KeyError(run_id)
        state.update(fields)
        save(state)
        return state


def list_runs() -> list[dict]:
    out = []
    if not RUNS.exists():
        return out
    for d in sorted(RUNS.iterdir(), reverse=True):
        s = load(d.name) if d.is_dir() else None
        if s:
            out.append(
                {
                    "run_id": s["run_id"],
                    "name": s["product"].get("name", s["run_id"]),
                    "profile": s["profile"],
                    "stage": s["stage"],
                    "status": s["status"],
                    "updated_at": s["updated_at"],
                    "usage": s["usage"],
                }
            )
    return out


def trace(run_id: str, kind: str, name: str = "", **fields: Any) -> None:
    """append-only 실행 로그. 화면의 트레이스 패널이 이 파일을 읽는다."""
    entry = {"at": now(), "ts": time.time(), "kind": kind, "name": name, **fields}
    with _lock:
        p = run_dir(run_id) / "trace.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_trace(run_id: str, after: int = 0) -> list[dict]:
    p = run_dir(run_id) / "trace.jsonl"
    if not p.exists():
        return []
    with _lock:
        lines = p.read_text(encoding="utf-8").splitlines()
    out = []
    for i, line in enumerate(lines):
        if i < after or not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry["seq"] = i + 1
        out.append(entry)
    return out


def add_artifact(run_id: str, rel_path: str, kind: str, size: int) -> None:
    with _lock:
        state = load(run_id)
        if state is None:
            return
        state["artifacts"] = [a for a in state["artifacts"] if a["path"] != rel_path]
        state["artifacts"].append(
            {"path": rel_path, "kind": kind, "bytes": size, "at": now()}
        )
        save(state)
