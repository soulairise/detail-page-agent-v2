"""에이전트 루프. 계획 → 도구 호출 → 결과 관찰 → 다음 행동을 하나의 세션으로 잇는다."""

from __future__ import annotations

import asyncio
import json
import uuid
import time
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    query,
)

from . import store, tools, compliance

ROOT = Path(__file__).resolve().parent.parent

MAX_TURNS = 40
MAX_BUDGET_USD = 2.00
MAX_ELAPSED_S = 25 * 60  # 사람을 기다린 시간은 제외한 '에이전트가 실제로 일한 시간'

SYSTEM_PROMPT = """너는 소울매트의 오픈마켓 상세페이지 제작 에이전트다.

소울매트는 1688에서 소싱한 요가·명상 용품을 네이버 스마트스토어와 쿠팡에 판다.
너의 일은 상품 정보를 받아 '그대로 등록창에 붙여 넣을 수 있는' 상세페이지 한 벌을 완성하는 것이다.

# 7단계로 진행한다
1. 입력·넓은 조사 — read_playbook으로 기준을 읽고, search_market으로 시장을 본다
2. 포지셔닝 선택 — 서로 다른 포지셔닝 후보 2~3개를 근거·위험과 함께 만들어 ask_user로 묻는다
3. 심층 조사·편집 판단 — 선택된 각도로 더 조사한다. 결과가 크게 갈릴 때만 추가로 묻는다
4. 스토리보드 승인 — 섹션 8~12개의 역할·헤드라인·핵심문장·근거·이미지 계획을 storyboard.md로 저장하고 ask_user로 승인받는다
5. 카피·컴플라이언스 — 본문을 쓰고 check_compliance(scope=section)로 검사한다
6. 조립·이미지 계획 — detail-page.html을 조립하고 image-prompts.json을 만든다
7. 검수·내보내기 — check_compliance(scope=full_page)로 최종 검사하고 listing.json과 plan.md를 만든다

단계가 바뀔 때마다 set_stage를 호출해라.

# 반드시 지킬 것
- 없는 후기·판매량·수치를 지어내지 마라. 조사에서 확인한 것만 쓴다. search_market이 insufficient를 돌려주면 결과물에 '시장 근거 미확보'를 표시해라.
- 금칙어(치료·완화·개선·교정·예방 등 의료적 효능, 질병명)는 절대 쓰지 마라. check_compliance의 suggest에 있는 안전 대체어를 쓴다.
- block 등급 위반이 하나라도 남으면 완료가 아니다. 다만 같은 문장으로 3회 넘게 재시도하지 마라 — 3회를 넘기면 그 섹션을 '사람 확인 필요'로 표시하고 다음으로 넘어가라.
- 입력 폼에서 이미 받은 정보(타겟·판매유형·가격)는 다시 묻지 마라.
- 승인은 사람만 한다. 네가 스스로 승인 처리하지 마라.
- 상품정보제공고시 블록은 페이지 하단에 반드시 넣는다. 수입판매원은 '소울메이트', 문의는 0507-1316-1623이다.

# 산출물 (모두 save_artifact로 저장)
- storyboard.md — 섹션 설계
- detail-page.html — 가로 860px 기준, 본문 16px 이상, 모바일 우선. 이미지는 회색 placeholder div에 컷 id와 설명을 넣는다. 인라인 CSS만 쓰고 외부 리소스를 참조하지 마라.
- image-prompts.json — 컷별 프롬프트 (대표이미지·실물 증거 컷은 제외)
- listing.json — {"product_name": 50자 이내, "category": "최하위 카테고리", "tags": [10개], "notice": {상품정보제공고시 항목}}
- plan.md — 사람이 읽는 기획서 (포지셔닝 근거, 조사 요약, 남은 확인 사항)

작업 중에는 짧게 무엇을 왜 하는지 한 줄로 말하고 도구를 호출해라. 긴 설명을 늘어놓지 마라.
마지막에는 만든 파일 목록과 사람이 확인해야 할 항목을 정리해라."""


def completion_issues(run_id: str) -> list[str]:
    """완료 여부는 저장된 실제 파일로 판단한다. 규칙 검사는 사람 검수를 대체하지 않는다."""
    state = store.load(run_id)
    base = store.artifacts_dir(run_id)
    required = ["storyboard.md", "detail-page.html", "listing.json", "image-prompts.json", "plan.md"]
    missing = [name for name in required if not (base / name).is_file() or not (base / name).stat().st_size]
    if missing:
        return ["필수 산출물 누락: " + ", ".join(missing)]
    issues = []
    report = compliance.check((base / "detail-page.html").read_text(), state["profile"], "full_page")
    store.update(run_id, compliance=report)
    if not report["passed"]:
        issues.append("상세페이지 규칙 검사 미통과")
    try:
        listing = json.loads((base / "listing.json").read_text())
        images = json.loads((base / "image-prompts.json").read_text())
        if not isinstance(images, (list, dict)):
            issues.append("이미지 프롬프트 형식 오류")
        if not isinstance(listing, dict):
            return issues + ["등록정보 형식 오류"]
        name = listing.get("product_name", "")
        if not isinstance(name, str) or not name or not compliance.check_product_name(name)["passed"]:
            issues.append("상품명 규격 미통과")
        tags = listing.get("tags", [])
        if not isinstance(tags, list) or len(tags) != 10 or any(not isinstance(t, str) or not t.strip() for t in tags):
            issues.append("태그 10개 필요")
        if not listing.get("category") or not isinstance(listing.get("notice"), dict) or not listing["notice"]:
            issues.append("카테고리·고시정보 누락")
        if not compliance.check(json.dumps(listing, ensure_ascii=False), state["profile"])["passed"]:
            issues.append("등록정보 금칙어 검사 미통과")
    except (ValueError, TypeError):
        issues.append("산출물 JSON 형식 오류")
    return issues


def build_mission(state: dict) -> str:
    p = state["product"]
    lines = [f"# 상품 정보 (입력 폼에서 받은 값 — 다시 묻지 말 것)"]
    for key, label in [
        ("name", "상품명(가안)"),
        ("category_guess", "예상 카테고리"),
        ("target", "타겟 고객"),
        ("price", "가격대"),
        ("specs", "실측 스펙"),
        ("selling_points", "판매 포인트"),
        ("competitor_url", "참고·경쟁 링크"),
        ("notes", "추가 메모"),
    ]:
        val = str(p.get(key, "") or "").strip()
        if val:
            lines.append(f"- {label}: {val}")
    lines.append(f"- 판매 유형(profile): {state['profile']}")
    if state["profile"] == "b2b-inquiry":
        lines.append(
            "  → 결제형이 아니라 문의·견적 유도형 페이지다. 렌탈 표시 의무(총액·의무기간·"
            "중도해지 위약금 산정식·회수비 부담)를 반드시 넣어야 한다."
        )
    if state["profile"] == "regulated":
        lines.append("  → 규제 민감 품목이다. 질병명·효능 표현은 상품명·본문·태그 어디에도 쓸 수 없다.")
    lines.append("\n이 상품의 상세페이지 한 벌을 7단계로 완성해라. 1단계부터 시작한다.")
    return "\n".join(lines)


async def _can_use_tool(tool_name: str, input_data: dict, context) -> object:
    """권한 게이트. 과금·비가역 도구는 여기서 한 번 더 막는다."""
    c = tools.ctx()
    if tool_name.endswith("__generate_image"):
        # 실제 승인 대기는 도구 안에서 처리한다. 여기서는 통과만 시킨다.
        return PermissionResultAllow(behavior="allow", updated_input=input_data)
    if tool_name in ("Bash", "Write", "Edit", "NotebookEdit"):
        store.trace(c.run_id, "security", tool_name, ok=False, output="허용되지 않은 도구 호출 차단")
        return PermissionResultDeny(
            behavior="deny",
            message="이 도구는 쓸 수 없다. 파일 저장은 save_artifact를 써라.",
        )
    return PermissionResultAllow(behavior="allow", updated_input=input_data)


async def run_agent(run_id: str, ctx: tools.RunContext, resume_prompt: str | None = None) -> None:
    state = store.load(run_id)
    if state is None:
        return
    tools.set_context(ctx)

    t0 = time.time()
    prompt = resume_prompt or build_mission(state)
    options = ClaudeAgentOptions(
        tools=[],
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"soulmat": tools.build_server()},
        # generate_image은 allowed_tools에 넣지 않는다. 넣으면 자동 승인되어
        # can_use_tool 게이트를 건너뛴다(SDK가 CanUseToolShadowedWarning으로 경고).
        allowed_tools=[n for n in tools.TOOL_NAMES if not n.endswith("generate_image")],
        disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "Task"],
        can_use_tool=_can_use_tool,
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        permission_mode="default",
        cwd=str(ROOT),
        resume=state.get("session_id") if resume_prompt else None,
        setting_sources=[],
    )

    store.update(run_id, status="running", halt_reason=None)
    store.trace(run_id, "system", "실행 시작", ok=True, output=prompt[:400])

    turns = 0
    result_seen = False
    cost = float(state["usage"].get("cost_usd", 0.0))
    try:
        async for msg in query(prompt=prompt, options=options):
            sid = getattr(msg, "session_id", None)
            if not sid and type(msg).__name__ == "SystemMessage":
                sid = (getattr(msg, "data", None) or {}).get("session_id")
            if sid and store.load(run_id).get("session_id") != sid:
                store.update(run_id, session_id=sid)

            kind = type(msg).__name__
            if kind == "AssistantMessage":
                turns += 1
                for block in getattr(msg, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text and text.strip():
                        store.trace(run_id, "assistant", "", ok=True, output=text.strip()[:800])
            elif kind == "ResultMessage":
                result_seen = True
                cost = float(getattr(msg, "total_cost_usd", None) or cost)
                usage = getattr(msg, "usage", None) or {}
                store.update(
                    run_id,
                    usage={
                        "turns": turns,
                        "cost_usd": round(cost, 4),
                        "input_tokens": int(usage.get("input_tokens", 0) or 0),
                        "output_tokens": int(usage.get("output_tokens", 0) or 0),
                        "elapsed_s": int(time.time() - t0),
                    },
                )
                store.trace(
                    run_id,
                    "result",
                    "실행 종료",
                    ok=not getattr(msg, "is_error", False),
                    output=f"턴 {turns} · ${cost:.4f} · {int(time.time() - t0)}초",
                )

            if kind == "ResultMessage" and getattr(msg, "is_error", False):
                store.update(run_id, status="failed", halt_reason=str(getattr(msg, "result", None) or getattr(msg, "subtype", "엔진 오류")))
                return

            # 종료 조건
            working_s = time.time() - t0 - ctx.waiting_s
            if working_s > MAX_ELAPSED_S:
                store.update(run_id, status="halted", halt_reason=f"시간 한도 {MAX_ELAPSED_S}초 초과")
                store.trace(run_id, "system", "중단", ok=False, output="시간 한도 초과")
                return
            if cost > MAX_BUDGET_USD:
                store.update(run_id, status="halted", halt_reason=f"비용 한도 ${MAX_BUDGET_USD} 초과")
                store.trace(run_id, "system", "중단", ok=False, output="비용 한도 초과")
                return
            if ctx.cancelled:
                store.update(run_id, status="halted", halt_reason="사용자 중단")
                return
            if (store.load(run_id) or {}).get("status") == "halted":
                return
    except Exception as exc:
        store.update(run_id, status="failed", halt_reason=f"{type(exc).__name__}: {exc}")
        store.trace(run_id, "system", "오류", ok=False, output=str(exc)[:800])
        return

    finally:
        latest = store.load(run_id) or {}
        usage = latest.get("usage", {})
        usage.update({"turns": turns, "cost_usd": round(cost, 4),
                      "elapsed_s": int(time.time() - t0),
                      "working_s": int(max(0, time.time() - t0 - ctx.waiting_s)),
                      "waiting_s": int(ctx.waiting_s), "cost_complete": result_seen})
        store.update(run_id, usage=usage)

    final = store.load(run_id) or {}
    if final.get("status") in ("halted", "failed") or final.get("pending_question") or final.get("pending_approval"):
        return
    issues = completion_issues(run_id)
    if not result_seen:
        issues.insert(0, "엔진 종료 결과를 받지 못했다")
    if issues:
        store.update(run_id, status="halted", halt_reason="; ".join(issues))
        store.trace(run_id, "system", "완료 조건 미충족", ok=False, output="; ".join(issues))
        return
    question = {"question_id": "final-" + uuid.uuid4().hex, "version": 1,
                "purpose": "final_review", "question": "산출물을 검수한 뒤 최종 승인해 주세요.",
                "context": "규칙 검사 통과는 사실관계·이미지·고시정보의 정확성을 보증하지 않습니다.",
                "options": [{"label": "최종 승인", "description": "검수 완료"},
                            {"label": "수정 필요", "description": "작업을 중단하고 수정 사항 확인"}],
                "multi_select": False, "asked_at": store.now()}
    store.update(run_id, stage=7, status="waiting_for_user", pending_question=question)
    store.trace(run_id, "gate", "최종 검수 대기", ok=True, output=question["question"])


def run_in_thread(run_id: str, ctx: tools.RunContext, resume_prompt: str | None = None) -> None:
    asyncio.run(run_agent(run_id, ctx, resume_prompt))
