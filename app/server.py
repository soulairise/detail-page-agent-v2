"""로컬 웹 서버. 화면과 에이전트 루프를 잇는다. http://127.0.0.1:8765"""

from __future__ import annotations

import io
import json
import re
import threading
import zipfile
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import agent, store, tools

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
HOST, PORT = "127.0.0.1", 8765

_contexts: dict[str, tools.RunContext] = {}
_lock = threading.RLock()

PROFILES = [
    {"id": "b2c-goods", "label": "일반 판매(B2C)", "desc": "결제형 상품 페이지"},
    {"id": "b2b-inquiry", "label": "문의·견적형(B2B)", "desc": "렌탈·대량 납품 등 문의 유도형"},
    {"id": "regulated", "label": "규제 민감", "desc": "네티팟 등 효능 표현 금지 품목"},
]

FIELDS = [
    {"key": "name", "label": "상품명(가안)", "required": True},
    {"key": "category_guess", "label": "예상 카테고리"},
    {"key": "target", "label": "타겟 고객", "multiline": True},
    {"key": "price", "label": "가격대"},
    {"key": "specs", "label": "실측 스펙(1688 등)", "multiline": True},
    {"key": "selling_points", "label": "판매 포인트", "multiline": True},
    {"key": "competitor_url", "label": "참고·경쟁 링크"},
    {"key": "notes", "label": "추가 메모", "multiline": True},
]


def slugify(name: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", name.strip().lower()).strip("-")
    return (s or "run")[:30]


def start_run(run_id: str, resume_prompt: str | None = None) -> bool:
    with _lock:
        if run_id in _contexts:
            return False
        state = store.load(run_id)
        if state is None:
            return False
        ctx = tools.RunContext(run_id=run_id, profile=state["profile"])
        _contexts[run_id] = ctx
        def worker():
            try:
                agent.run_in_thread(run_id, ctx, resume_prompt)
            finally:
                with _lock:
                    if _contexts.get(run_id) is ctx:
                        _contexts.pop(run_id, None)
        threading.Thread(target=worker, daemon=True).start()
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "SoulmatDetailAgent/2.0"

    def log_message(self, fmt, *args):  # 조용히
        pass

    # ---------- helpers ----------
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        path, qs = unquote(u.path), parse_qs(u.query)

        if path in ("/", "/index.html"):
            return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path in ("/demo", "/demo/"):
            demo = ROOT / "docs" / "index.html"
            if not demo.is_file():
                return self._json({"error": "데모를 먼저 빌드해라"}, 404)
            return self._send(200, demo.read_bytes(), "text/html; charset=utf-8")
        if path.startswith("/demo/artifacts/"):
            base = (ROOT / "docs" / "artifacts").resolve()
            target = (base / path[len("/demo/artifacts/"):]).resolve()
            if not target.is_relative_to(base) or not target.is_file():
                return self._json({"error": "not found"}, 404)
            ctype = "text/html; charset=utf-8" if target.suffix == ".html" else "text/plain; charset=utf-8"
            return self._send(200, target.read_bytes(), ctype)
        if path == "/api/meta":
            return self._json({"profiles": PROFILES, "fields": FIELDS, "stages": store.STAGES})
        if path == "/api/runs":
            return self._json({"runs": store.list_runs()})

        m = re.match(r"^/api/run/([\w\-]+)$", path)
        if m:
            state = store.load(m.group(1))
            if state is None:
                return self._json({"error": "not found"}, 404)
            state["live"] = m.group(1) in _contexts
            return self._json(state)

        m = re.match(r"^/api/run/([\w\-]+)/trace$", path)
        if m:
            after = int((qs.get("after") or ["0"])[0])
            return self._json({"entries": store.read_trace(m.group(1), after)})

        m = re.match(r"^/api/run/([\w\-]+)/artifact/(.+)$", path)
        if m:
            run_id, rel = m.group(1), unquote(m.group(2))
            base = store.artifacts_dir(run_id).resolve()
            target = (base / rel).resolve()
            if not target.is_relative_to(base) or not target.is_file():
                return self._json({"error": "not found"}, 404)
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".md": "text/plain; charset=utf-8",
                ".png": "image/png",
            }.get(target.suffix, "text/plain; charset=utf-8")
            return self._send(200, target.read_bytes(), ctype)

        m = re.match(r"^/api/run/([\w\-]+)/export$", path)
        if m:
            run_id = m.group(1)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                d = store.run_dir(run_id)
                for p in d.rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(d))
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{run_id}.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)

        return self._json({"error": "not found"}, 404)

    # ---------- POST ----------
    def do_POST(self):
        with _lock:
            return self._post_locked()

    def _post_locked(self):
        path = unquote(urlparse(self.path).path)
        body = self._body()

        if path == "/api/runs":
            product = body.get("product") or {}
            if not product.get("name"):
                return self._json({"error": "상품명은 필수다"}, 400)
            profile = body.get("profile") or "b2c-goods"
            run_id = f"{slugify(product['name'])}-{datetime.now().strftime('%m%d-%H%M')}-{uuid.uuid4().hex[:8]}"
            store.create_run(run_id, product, profile)
            start_run(run_id)
            return self._json({"run_id": run_id})

        m = re.match(r"^/api/run/([\w\-]+)/(answer|approve|resume|cancel)$", path)
        if not m:
            return self._json({"error": "not found"}, 404)
        run_id, action = m.group(1), m.group(2)
        state = store.load(run_id)
        if state is None:
            return self._json({"error": "not found"}, 404)
        ctx = _contexts.get(run_id)

        if action == "answer":
            previous = next((a for a in state.get("answers", [])
                if a["question_id"] == body.get("question_id") and a["version"] == body.get("version")), None)
            if previous:
                if previous["answer"] != body.get("answer"):
                    return self._json({"error": "이미 다른 답변이 저장됐다"}, 409)
                return self._json({"ok": True, "duplicate": True})
            q = state.get("pending_question")
            if not q or body.get("question_id") != q["question_id"] or body.get("version") != q["version"]:
                return self._json({"error": "지난 질문에 대한 답변이다. 화면을 새로고침해라."}, 409)
            answer = body.get("answer")
            if not answer:
                return self._json({"error": "답변은 필수다"}, 400)
            if q.get("purpose") == "final_review":
                if answer not in (["최종 승인"], ["수정 필요"]):
                    return self._json({"error": "최종 승인 또는 수정 필요를 선택해라"}, 400)
                if answer == ["최종 승인"]:
                    issues = agent.completion_issues(run_id)
                    if issues:
                        return self._json({"error": "산출물 재검사 실패", "issues": issues}, 409)
            entry = {"question_id": q["question_id"], "version": q["version"],
                     "question": q["question"], "answer": answer, "answered_at": store.now()}
            store.update(run_id, pending_question=None, answers=state.get("answers", []) + [entry])
            store.trace(run_id, "gate", "답변 접수", ok=True, output=str(answer))
            if q.get("purpose") == "final_review":
                approved = answer == ["최종 승인"]
                store.update(run_id, status="done" if approved else "halted",
                             halt_reason=None if approved else "사용자 수정 요청")
                return self._json({"ok": True})
            if ctx is None:
                start_run(run_id, resume_prompt=f'앞서 물었던 "{q["question"]}"에 대한 사용자의 답은 "{answer}"다. 이 답을 반영해 이어가라.')
                return self._json({"ok": True, "resumed": True})
            ctx.answer = answer
            ctx.answer_event.set()
            return self._json({"ok": True})

        if action == "approve":
            if not state.get("pending_approval"):
                return self._json({"error": "대기 중인 승인이 없다"}, 409)
            if ctx is None:
                if body.get("approved") is False:
                    store.update(run_id, pending_approval=None, status="halted", halt_reason="중단된 이미지 승인 취소")
                    store.trace(run_id, "gate", "이미지 승인 취소", ok=True, output="재시작 후 사용자가 거절")
                    return self._json({"ok": True})
                return self._json({"error": "실행이 종료됐다. 먼저 이미지 승인을 거절한 뒤 재개해라."}, 409)
            if ctx.approval_event.is_set():
                return self._json({"ok": True, "duplicate": True})
            if not isinstance(body.get("approved"), bool):
                return self._json({"error": "approved는 true 또는 false여야 한다"}, 400)
            ctx.approval = body["approved"]
            ctx.approval_event.set()
            return self._json({"ok": True})

        if action == "cancel":
            if ctx:
                ctx.cancelled = True
                ctx.answer_event.set()
                ctx.approval_event.set()
            store.update(run_id, status="halted", halt_reason="사용자 중단")
            return self._json({"ok": True})

        if action == "resume":
            q = state.get("pending_question")
            hint = body.get("prompt") or "중단된 지점부터 작업을 이어가라."
            if q or state.get("pending_approval"):
                return self._json({"error": "먼저 대기 중인 질문에 답해라."}, 409)
            if not start_run(run_id, resume_prompt=hint):
                return self._json({"error": "이미 실행 중이다"}, 409)
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)


def main():
    store.RUNS.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"소울매트 상세페이지 에이전트 V2 → http://{HOST}:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
