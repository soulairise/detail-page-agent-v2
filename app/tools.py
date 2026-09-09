"""에이전트가 쓰는 도구 7개. 각 도구는 스키마·실패 처리·권한 범위를 갖는다."""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query, tool

from . import compliance, store

ROOT = Path(__file__).resolve().parent.parent
QUESTION_TIMEOUT_S = 60 * 60


@dataclass
class RunContext:
    """실행 하나의 공유 상태. 도구와 서버 스레드가 이 객체로 대화한다."""

    run_id: str
    profile: str
    answer_event: threading.Event = field(default_factory=threading.Event)
    answer: Any = None
    approval_event: threading.Event = field(default_factory=threading.Event)
    approval: bool | None = None
    question_seq: int = 0
    cancelled: bool = False
    consecutive_failures: int = 0
    waiting_s: float = 0.0  # 사람을 기다린 시간. 에이전트 시간 예산에서 제외한다.


_ctx: contextvars.ContextVar[RunContext] = contextvars.ContextVar("run_ctx")


def set_context(ctx: RunContext) -> None:
    _ctx.set(ctx)


def ctx() -> RunContext:
    return _ctx.get()


def _ok(payload: dict) -> dict:
    """MCP 도구 반환 규약: content 블록으로 감싼다."""
    return {
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
        ]
    }


def _timed(name: str):
    """도구 호출을 trace.jsonl에 남기는 데코레이터."""

    def deco(fn):
        async def wrapper(args: dict) -> dict:
            c = ctx()
            if c.cancelled or (store.load(c.run_id) or {}).get("status") == "halted":
                return _ok({"error": "중단된 실행이다"})
            t0 = time.time()
            try:
                payload = await fn(args)
                ok = not payload.get("error")
            except Exception as exc:  # 도구 예외를 에이전트가 관찰할 수 있게 되돌린다
                payload = {"error": f"{type(exc).__name__}: {exc}"}
                ok = False
            c.consecutive_failures = 0 if ok else c.consecutive_failures + 1
            if c.consecutive_failures >= 3:
                store.update(c.run_id, status="halted", halt_reason="도구 연속 실패 3회")
            store.trace(
                c.run_id,
                "tool",
                name,
                ok=ok,
                ms=int((time.time() - t0) * 1000),
                input=_summarize(args),
                output=_summarize(payload),
            )
            return _ok(payload)

        return wrapper

    return deco


def _summarize(obj: Any, limit: int = 600) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except TypeError:
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + f"… (+{len(s) - limit}자)"


def _extract_json(text: str) -> dict | None:
    fenced = re.findall(r"```(?:json)?\s*(.+?)```", text, flags=re.S)
    for candidate in reversed(fenced):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    depth = 0
    start = None
    best = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                best = text[start : i + 1]
    if best:
        try:
            return json.loads(best)
        except json.JSONDecodeError:
            return None
    return None


# --------------------------------------------------------------------------
# 1. search_market — 시장 조사 (외부 읽기, 자동 허용)
# --------------------------------------------------------------------------

SEARCH_SCHEMA = {
    "query": str,
    "channel": str,  # naver | coupang | web
    "days": int,
    "max_results": int,
}


@tool(
    "search_market",
    "네이버·쿠팡·웹에서 경쟁 상품, 가격대, 상품명 패턴, 리뷰 불만을 조사한다. "
    "상품 포지셔닝을 정하거나 시장 근거가 필요할 때 쓴다. "
    "channel은 naver/coupang/web 중 하나, days는 조사 기간(일). "
    "결과가 부족하면 insufficient=true로 돌아오며, 이때 없는 내용을 지어내면 안 된다.",
    SEARCH_SCHEMA,
)
@_timed("search_market")
async def search_market(args: dict) -> dict:
    q = args.get("query", "").strip()
    channel = args.get("channel", "web")
    days = int(args.get("days", 90) or 90)
    max_results = int(args.get("max_results", 8) or 8)
    if not q:
        return {"error": "query가 비어 있다"}

    site = {"naver": "네이버쇼핑 스마트스토어", "coupang": "쿠팡"}.get(channel, "")
    prompt = (
        f"'{q}' 를 {site} 중심으로 웹 검색해서 최근 {days}일 기준 시장 현황을 조사해라.\n"
        f"경쟁 상품 최대 {max_results}개의 제목·가격·URL·리뷰수와, 리뷰에서 반복되는 불만 키워드를 찾아라.\n"
        "검색 결과에서 확인한 것만 적고 추정치는 넣지 마라. 자료를 찾지 못하면 insufficient를 true로 둬라.\n"
        "마지막에 아래 JSON만 코드블록으로 출력해라.\n"
        '{"results":[{"title":"","url":"","price":"","review_count":"","snippet":""}],'
        '"complaint_keywords":[""],"price_range":"","insufficient":false,"note":""}'
    )
    # 조사는 별도 세션(리서처 역할)으로 분리한다. 실패해도 본 실행을 멈추지 않는다.
    for attempt in (1, 2):
        try:
            text = []
            async for msg in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    tools=["WebSearch", "WebFetch"],
                    allowed_tools=["WebSearch", "WebFetch"],
                    setting_sources=[],
                    cwd=str(ROOT),
                    permission_mode="bypassPermissions",
                    max_turns=8,
                    max_budget_usd=0.5,
                    system_prompt="너는 한국 오픈마켓 시장 조사원이다. 확인한 사실만 보고한다.",
                ),
            ):
                for block in getattr(msg, "content", []) or []:
                    if getattr(block, "text", None):
                        text.append(block.text)
            data = _extract_json("\n".join(text))
            if data is None:
                if attempt == 1:
                    continue
                return {
                    "insufficient": True,
                    "results": [],
                    "error": "조사 결과를 JSON으로 해석하지 못했다",
                }
            data.setdefault("results", [])
            data["as_of"] = store.now()
            data["period_days"] = days
            data["channel"] = channel
            data.setdefault("insufficient", not data["results"])
            return data
        except Exception as exc:
            if attempt == 2:
                return {
                    "insufficient": True,
                    "results": [],
                    "error": f"검색 실패: {exc}. 시장 근거 없이 진행하되 결과물에 '시장 근거 미확보'를 표시할 것",
                }
            await asyncio.sleep(1)
    return {"insufficient": True, "results": []}


# --------------------------------------------------------------------------
# 2. read_playbook — 도메인 지식 조회 (로컬 읽기, 지정 파일만)
# --------------------------------------------------------------------------


@tool(
    "read_playbook",
    "소울매트 요가용품 플레이북과 규정 사전을 읽는다. "
    "section: playbook(전문) / forbidden_words(금칙어) / listing_spec(상품명·태그·이미지 규격) / "
    "required_blocks(상품정보제공고시·렌탈 표시 의무) / image_rules. "
    "페이지 구조를 짜기 전, 카피를 쓰기 전에 반드시 확인한다.",
    {"section": str},
)
@_timed("read_playbook")
async def read_playbook(args: dict) -> dict:
    section = args.get("section", "playbook")
    rules = compliance.load_rules()
    if section == "playbook":
        text = (ROOT / "knowledge" / "playbook.md").read_text(encoding="utf-8")
        return {"section": section, "source": "knowledge/playbook.md", "content": text}
    if section in ("forbidden_words", "word_rules"):
        return {"section": section, "source": "knowledge/rules.json", "content": rules["word_rules"]}
    if section in rules:
        return {"section": section, "source": "knowledge/rules.json", "content": rules[section]}
    return {
        "error": f"알 수 없는 section: {section}",
        "available": ["playbook", "forbidden_words", "listing_spec", "required_blocks", "image_rules", "company"],
    }


# --------------------------------------------------------------------------
# 3. check_compliance — 규정 검사 (순수 함수, 자동 허용)
# --------------------------------------------------------------------------


@tool(
    "check_compliance",
    "작성한 문구가 금칙어·규제를 어기는지 검사한다. LLM 판단이 아니라 규칙 사전 기반이다. "
    "scope=section은 문구만, scope=full_page는 상품정보제공고시·렌탈 표시 의무 누락까지 본다. "
    "카피를 쓴 직후와 페이지를 조립한 뒤 반드시 호출한다. "
    "severity=block 위반이 하나라도 남으면 그 페이지는 완성이 아니다.",
    {"text": str, "scope": str},
)
@_timed("check_compliance")
async def check_compliance(args: dict) -> dict:
    text = args.get("text", "")
    if not text:
        return {"error": "text가 비어 있다"}
    scope = args.get("scope", "section")
    c = ctx()
    report = compliance.check(text, profile=c.profile, scope=scope)
    if scope == "full_page":
        store.update(c.run_id, compliance=report)
    if not report["passed"]:
        report["next_action"] = (
            "block 위반은 suggest의 대체 표현으로 바꾸고 다시 검사해라. "
            "누락 항목은 해당 블록을 추가해라. 같은 문구로 3회 넘게 재시도하지 마라."
        )
    return report


# --------------------------------------------------------------------------
# 4. save_artifact — 산출물 저장 (쓰기, 실행 폴더 내부로 제한)
# --------------------------------------------------------------------------


@tool(
    "save_artifact",
    "산출물 파일을 저장한다. path는 실행 폴더 기준 상대경로만 허용한다(절대경로·상위경로 거부). "
    "detail-page.html(상세페이지), listing.json(상품명·태그·카테고리·고시정보), "
    "storyboard.md(섹션 설계), image-prompts.json(컷별 프롬프트), plan.md(기획서)를 만든다.",
    {"path": str, "content": str, "kind": str},
)
@_timed("save_artifact")
async def save_artifact(args: dict) -> dict:
    c = ctx()
    rel = (args.get("path") or "").strip()
    content = args.get("content") or ""
    if not rel:
        return {"error": "path가 비어 있다"}

    base = store.artifacts_dir(c.run_id).resolve()
    raw = base / rel
    if Path(rel).is_absolute() or ".." in Path(rel).parts or any(x.is_symlink() for x in [raw, *raw.parents] if x == base or x.is_relative_to(base)):
        store.trace(c.run_id, "security", "save_artifact", ok=False, output=f"경로 거부: {rel}")
        return {"error": "절대경로·상위경로·심볼릭 링크는 허용되지 않는다"}
    target = raw.resolve()
    if not str(target).startswith(str(base) + "/") and target != base:
        store.trace(c.run_id, "security", "save_artifact", ok=False, output=f"경로 이탈 거부: {rel}")
        return {"error": f"실행 폴더 밖으로는 쓸 수 없다: {rel}", "allowed_root": "artifacts/"}
    if target.is_symlink():
        return {"error": "심볼릭 링크에는 쓸 수 없다"}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    kind = args.get("kind") or target.suffix.lstrip(".")
    store.add_artifact(c.run_id, rel, kind, len(content.encode("utf-8")))
    return {"ok": True, "path": rel, "bytes": len(content.encode("utf-8"))}


# --------------------------------------------------------------------------
# 5. generate_image — 이미지 생성 (과금·비가역, 사람 승인 필수)
# --------------------------------------------------------------------------


@tool(
    "generate_image",
    "OpenAI 이미지 API로 컷을 생성한다. 과금되는 도구라 사람 승인 없이는 실행되지 않는다. "
    "대표이미지(썸네일)와 실물·실측 증거 컷은 생성하지 않는다. "
    "생성 이미지는 네이버 AI 생성물 표시 의무 대상이므로 페이지에 표시를 붙여야 한다.",
    {"cut_id": str, "prompt": str, "size": str, "n": int},
)
@_timed("generate_image")
async def generate_image(args: dict) -> dict:
    c = ctx()
    c.approval = None
    c.approval_event.clear()
    cut_id = args.get("cut_id", "cut")
    est = 0.19 * int(args.get("n", 1) or 1)
    store.update(
        c.run_id,
        status="waiting_for_user",
        pending_approval={
            "tool": "generate_image",
            "cut_id": cut_id,
            "prompt": args.get("prompt", ""),
            "size": args.get("size", "1024x1536"),
            "n": args.get("n", 1),
            "est_cost_usd": round(est, 2),
            "asked_at": store.now(),
        },
    )
    store.trace(c.run_id, "gate", "generate_image 승인 대기", ok=True, output=f"{cut_id} 예상 ${est:.2f}")

    _w0 = time.time()
    granted = await asyncio.to_thread(c.approval_event.wait, QUESTION_TIMEOUT_S)
    c.waiting_s += time.time() - _w0
    if c.cancelled:
        return {"error": "사용자 중단"}
    approved = bool(c.approval) if granted else False
    store.update(c.run_id, status="running", pending_approval=None)
    if not approved:
        return {
            "ok": False,
            "denied": True,
            "note": "사용자가 이미지 생성을 승인하지 않았다. placeholder로 두고 image-prompts.json에 프롬프트만 남겨라.",
        }
    return {
        "ok": False,
        "note": "승인됨. MVP 범위에서 실제 생성은 gen_image.py 수동 실행으로 처리한다. "
        "image-prompts.json에 이 컷을 기록하고 페이지에는 placeholder를 넣어라.",
        "ai_generated_notice_required": True,
    }


# --------------------------------------------------------------------------
# 6. ask_user — 사람에게 묻고 답을 기다린다 (에이전트 루프 중단점)
# --------------------------------------------------------------------------


@tool(
    "ask_user",
    "사용자에게 묻고 답을 받을 때까지 작업을 멈춘다. "
    "결과가 크게 달라지는 지점에서만 쓴다(포지셔닝 선택, 스토리보드 승인, 구조를 바꾸는 판단). "
    "입력 폼에서 이미 받은 정보는 다시 묻지 않는다. options는 2~4개로 짧게 준다.",
    {"question": str, "options": list, "multi_select": bool, "context": str},
)
@_timed("ask_user")
async def ask_user(args: dict) -> dict:
    c = ctx()
    c.question_seq += 1
    c.answer = None
    c.answer_event.clear()
    options = args.get("options") or []
    normalized = []
    for opt in options:
        if isinstance(opt, dict):
            normalized.append(
                {"label": str(opt.get("label", "")), "description": str(opt.get("description", ""))}
            )
        else:
            normalized.append({"label": str(opt), "description": ""})

    question = {
        "question_id": f"q-{uuid.uuid4().hex}",
        "version": 1,
        "question": args.get("question", ""),
        "context": args.get("context", ""),
        "options": normalized,
        "multi_select": bool(args.get("multi_select", False)),
        "asked_at": store.now(),
    }
    store.update(c.run_id, status="waiting_for_user", pending_question=question)
    store.trace(c.run_id, "gate", "사용자 질문", ok=True, output=question["question"])

    _w0 = time.time()
    got = await asyncio.to_thread(c.answer_event.wait, QUESTION_TIMEOUT_S)
    c.waiting_s += time.time() - _w0
    if not got:
        store.update(c.run_id, status="halted", halt_reason="사용자 응답 시간 초과")
        return {"error": "응답 시간 초과. 작업을 중단한다."}

    if c.cancelled:
        return {"error": "사용자 중단"}
    store.update(c.run_id, status="running")
    return {"answer": c.answer, "question_id": question["question_id"]}


# --------------------------------------------------------------------------
# 7. set_stage — 진행 단계 보고 (관찰 가능성)
# --------------------------------------------------------------------------


@tool(
    "set_stage",
    "현재 진행 단계를 보고한다. 단계가 바뀔 때마다 호출한다. "
    "1 입력·넓은조사 / 2 포지셔닝선택 / 3 심층조사 / 4 스토리보드승인 / 5 카피·컴플라이언스 / "
    "6 조립·이미지계획 / 7 검수·내보내기",
    {"stage": int, "note": str},
)
@_timed("set_stage")
async def set_stage(args: dict) -> dict:
    c = ctx()
    stage = max(1, min(7, int(args.get("stage", 1) or 1)))
    note = args.get("note", "")
    store.update(c.run_id, stage=stage, stage_note=note)
    return {"ok": True, "stage": stage, "stage_name": store.STAGES[stage - 1]}


ALL_TOOLS = [
    search_market,
    read_playbook,
    check_compliance,
    save_artifact,
    generate_image,
    ask_user,
    set_stage,
]

TOOL_NAMES = [f"mcp__soulmat__{t.name}" for t in ALL_TOOLS]


def build_server():
    return create_sdk_mcp_server(name="soulmat", version="2.0.0", tools=ALL_TOOLS)
