#!/usr/bin/env python3
"""상세페이지 이미지 생성기 — OpenAI Images API (표준 라이브러리만 사용)

공장 사진을 참조로 넣어 장면 컷을 생성한다. 참조가 있으면 /v1/images/edits,
없으면 /v1/images/generations 를 쓴다.

사용법:
  python3 gen_image.py --spec <제품>/image-prompts.json           # 스펙 파일 일괄 생성
  python3 gen_image.py --spec ... --only 01_hero                  # 한 컷만
  python3 gen_image.py --spec ... --only 01_hero --n 3            # 후보 3장
  python3 gen_image.py --check                                     # 키·연결만 확인

키는 app/.env 의 OPENAI_API_KEY 또는 환경변수에서 읽는다. 화면에 출력하지 않는다.
"""
import argparse
import base64
import io
import json
import mimetypes
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parent
ENV_FILE = APP / ".env"
API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-1.5"
# 이 순서로 폴백한다. 조직 접근 권한에 따라 상위 모델이 막힐 수 있다.
MODEL_FALLBACK = ["gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"]


def load_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def build_multipart(fields, files):
    """fields: {name: str}, files: [(name, path)] → (content_type, body bytes)"""
    boundary = "----soulmat" + uuid.uuid4().hex
    buf = io.BytesIO()

    def w(s):
        buf.write(s.encode("utf-8") if isinstance(s, str) else s)

    for name, value in fields.items():
        if value is None:
            continue
        w(f"--{boundary}\r\n")
        w(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        w(f"{value}\r\n")
    for name, path in files:
        p = Path(path)
        ctype = mimetypes.guess_type(p.name)[0] or "image/png"
        w(f"--{boundary}\r\n")
        w(f'Content-Disposition: form-data; name="{name}"; filename="{p.name}"\r\n')
        w(f"Content-Type: {ctype}\r\n\r\n")
        w(p.read_bytes())
        w("\r\n")
    w(f"--{boundary}--\r\n")
    return f"multipart/form-data; boundary={boundary}", buf.getvalue()


def call_api(key, path, ctype, body, timeout=300):
    req = urllib.request.Request(
        API_BASE + path, data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": ctype},
        method="POST")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.load(r)


def api_error_text(e):
    try:
        payload = json.loads(e.read().decode("utf-8"))
        return payload.get("error", {}).get("message", str(payload))[:400]
    except Exception:
        return f"HTTP {e.code}"


def generate(key, prompt, refs, size, quality, n, model=None, timeout=300):
    """refs가 있으면 edits, 없으면 generations. 모델 폴백 포함."""
    models = [model] if model else MODEL_FALLBACK
    last_err = None
    for m in models:
        fields = {"model": m, "prompt": prompt, "size": size,
                  "quality": quality, "n": str(n)}
        if refs:
            files = [("image[]", r) for r in refs]
            ctype, body = build_multipart(fields, files)
            path = "/images/edits"
        else:
            ctype, body = build_multipart(fields, [])
            path = "/images/generations"
        try:
            resp = call_api(key, path, ctype, body, timeout)
            return m, resp
        except urllib.error.HTTPError as e:
            last_err = f"{m}: {api_error_text(e)}"
            # 권한/모델 문제면 다음 모델로, 그 외(잔액·정책)는 즉시 중단
            if e.code in (400, 403, 404) and model is None:
                print(f"  [폴백] {last_err}")
                continue
            raise RuntimeError(last_err) from None
    raise RuntimeError(last_err or "모든 모델 실패")


def save_images(resp, out_dir, base_name, ext="png"):
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    data = resp.get("data", [])
    for i, item in enumerate(data):
        b64 = item.get("b64_json")
        if not b64:
            continue
        suffix = "" if len(data) == 1 else f"_{chr(ord('a') + i)}"
        path = out_dir / f"{base_name}{suffix}.{ext}"
        path.write_bytes(base64.b64decode(b64))
        saved.append(path)
    return saved


def cmd_check(key):
    if not key:
        print("키 없음: app/.env 에 OPENAI_API_KEY=... 한 줄을 넣어 주세요.")
        return 1
    print(f"키 감지됨 (끝 4자리 …{key[-4:]}). 모델 접근 확인 중…")
    req = urllib.request.Request(API_BASE + "/models",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            ids = {m["id"] for m in json.load(r).get("data", [])}
    except urllib.error.HTTPError as e:
        print("연결 실패:", api_error_text(e))
        return 1
    avail = [m for m in MODEL_FALLBACK if m in ids]
    print("사용 가능한 이미지 모델:", ", ".join(avail) if avail else "없음(권한 확인 필요)")
    return 0 if avail else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", help="image-prompts.json 경로")
    ap.add_argument("--only", help="컷 id 하나만 생성")
    ap.add_argument("--n", type=int, help="후보 장수 (스펙값 덮어쓰기)")
    ap.add_argument("--model", help="모델 고정 (기본: 자동 폴백)")
    ap.add_argument("--check", action="store_true", help="키·모델 접근만 확인")
    args = ap.parse_args()

    key = load_key()
    if args.check or not args.spec:
        return cmd_check(key)
    if not key:
        print("키 없음: app/.env 에 OPENAI_API_KEY=... 를 넣어 주세요.")
        return 1

    spec_path = Path(args.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    base = spec_path.parent
    out_dir = (base / spec.get("output_dir", "images")).resolve()
    ref_dir = (base / spec.get("ref_dir", "refs")).resolve()

    cuts = spec["cuts"]
    if args.only:
        cuts = [c for c in cuts if c["id"] == args.only]
        if not cuts:
            print(f"컷 '{args.only}' 없음. 가능한 id: " +
                  ", ".join(c["id"] for c in spec["cuts"]))
            return 1

    style = spec.get("style_suffix", "")
    total_saved = []
    for c in cuts:
        refs = []
        for r in c.get("refs", []):
            p = ref_dir / r
            if not p.is_file():
                print(f"  [건너뜀] 참조 사진 없음: {p}")
                continue
            refs.append(str(p))
        prompt = (c["prompt"] + ("\n\n" + style if style else "")).strip()
        n = args.n or c.get("n", 1)
        print(f"\n[{c['id']}] {c.get('label', '')} — 참조 {len(refs)}장, {n}장 생성")
        t0 = time.time()
        try:
            model, resp = generate(
                key, prompt, refs,
                c.get("size", spec.get("size", "1536x1024")),
                c.get("quality", spec.get("quality", "high")),
                n, args.model)
        except RuntimeError as e:
            print(f"  실패: {e}")
            continue
        saved = save_images(resp, out_dir, c["id"])
        total_saved += saved
        usage = resp.get("usage", {})
        print(f"  {model} · {time.time() - t0:.0f}초 · 토큰 {usage.get('total_tokens', '?')}")
        for s in saved:
            print(f"  저장: {s.relative_to(base) if base in s.parents else s}")

    print(f"\n완료: {len(total_saved)}장 → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
