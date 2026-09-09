# API_SPEC — 화면과 서버의 약속

베이스: `http://127.0.0.1:8765` · 모든 응답은 `application/json; charset=utf-8`
화면은 실행 보드에서 **1.5초마다** `/api/run/<id>`와 `/api/run/<id>/trace?after=N`을 폴링한다.

## 조회

### `GET /api/meta`
화면이 입력 폼을 그리기 위한 정의.
```json
{ "profiles": [{"id":"b2c-goods","label":"일반 판매(B2C)","desc":"..."}],
  "fields":   [{"key":"name","label":"상품명(가안)","required":true,"multiline":false}],
  "stages":   ["입력·넓은 조사","포지셔닝 선택","심층 조사·편집 판단","스토리보드 승인","카피·컴플라이언스","조립·이미지 계획","검수·내보내기"] }
```

### `GET /api/runs`
```json
{ "runs": [{"run_id":"...","name":"...","profile":"b2b-inquiry","stage":3,
            "status":"waiting_for_user","updated_at":"...","usage":{...}}] }
```

### `GET /api/run/<run_id>` — 실행 상태 (단일 진실 원본)
```json
{ "run_id":"...", "product":{...}, "profile":"b2b-inquiry",
  "stage":4, "stage_note":"스토리보드 승인 대기",
  "status":"idle|running|waiting_for_user|done|failed|halted",
  "session_id":"엔진 세션 ID (재개에 사용)",
  "pending_question":{"question_id":"q002","version":1,"question":"...",
                      "context":"...","options":[{"label","description"}],
                      "multi_select":false,"asked_at":"..."},
  "pending_approval":{"tool":"generate_image","cut_id":"01_hero",
                      "prompt":"...","n":1,"est_cost_usd":0.19},
  "answers":[{"question_id","version","question","answer","answered_at"}],
  "artifacts":[{"path":"detail-page.html","kind":"html","bytes":48213,"at":"..."}],
  "compliance":{"passed":false,"block_count":0,"warn_count":2,
                "rules_applied":5,"violations":[...],"missing_required":[...]},
  "usage":{"turns":18,"cost_usd":0.42,"input_tokens":0,"output_tokens":0,"elapsed_s":214},
  "halt_reason":null, "live":true }
```
`live`는 이 실행의 스레드가 메모리에 살아 있는지다. `false`면 서버가 재시작된 것이므로 답변 제출 시 `resume` 경로를 탄다.

### `GET /api/run/<run_id>/trace?after=<seq>`
`seq` 다음 항목만 증분으로 준다.
```json
{ "entries": [{"seq":42,"at":"2026-09-09T15:41:08+09:00","kind":"tool|assistant|gate|system|result|security",
               "name":"check_compliance","ok":true,"ms":3,
               "input":"{...요약...}","output":"{...요약...}"}] }
```

### `GET /api/run/<run_id>/artifact/<상대경로>`
산출물 원본. `runs/<run_id>/artifacts/` 밖은 404. 화면은 `detail-page.html`을 iframe으로 미리보기한다.

### `GET /api/run/<run_id>/export`
실행 폴더 전체(state·trace·artifacts)를 ZIP으로. `Content-Disposition: attachment`.

## 실행 제어

### `POST /api/runs` — 실행 생성과 동시에 시작
```json
요청 { "profile":"b2b-inquiry", "product":{"name":"...","target":"...", ...} }
응답 { "run_id":"요가매트-렌탈-0909-1542" }        // 400: 상품명 누락
```

### `POST /api/run/<run_id>/answer` — 질문에 답한다
```json
요청 { "question_id":"q002", "version":1, "answer":["행사·기업 웰니스 중심"] }
응답 { "ok":true }                      // 서버 재시작 후라면 {"ok":true,"resumed":true}
     { "ok":true,"duplicate":true }     // 이미 제출됨 — 재실행하지 않는다
     409 { "error":"지난 질문에 대한 답변이다. 화면을 새로고침해라." }
```
**멱등 규칙**: `question_id`와 `version`이 현재 대기 질문과 일치해야 받는다. 지난 질문의 뒤늦은 답변은 현재 작업을 덮어쓰지 않는다. 같은 답을 두 번 보내도 작업은 한 번만 이어진다.

### `POST /api/run/<run_id>/approve` — 과금 도구 승인
```json
요청 { "approved": true }
응답 { "ok":true } / { "ok":true,"duplicate":true } / 409 { "error":"대기 중인 승인이 없다" }
```

### `POST /api/run/<run_id>/resume` — 중단된 실행 재개
저장된 `session_id`로 엔진 세션을 이어 새 스레드를 띄운다.
```json
요청 { "prompt": "중단된 지점부터 작업을 이어가라." }   // 생략 가능
응답 { "ok":true } / 409 { "error":"먼저 대기 중인 질문에 답해라." }
```

### `POST /api/run/<run_id>/cancel`
`status`를 `halted`로 바꾸고 다음 관찰 지점에서 루프를 멈춘다.

## 상태 전이

```
idle ──실행──▶ running ──ask_user/generate_image──▶ waiting_for_user
                  │                                      │ answer·approve
                  │◀─────────────────────────────────────┘
                  ├──완료──▶ done
                  ├──예외──▶ failed        (halt_reason에 원인)
                  └──한도/중단──▶ halted    (턴 40 · $2.00 · 15분 · 사용자 중단)
```

## 오류 규약

| 코드 | 상황 |
|---|---|
| 400 | 필수 입력 누락 |
| 404 | 없는 실행·없는 산출물·허용되지 않은 경로 |
| 409 | 상태 충돌 (대기 질문 없음, 지난 질문에 답변, 실행이 살아 있지 않음) |

엔진 출력이 규약을 어기면 **완료로 처리하지 않는다.** `status`를 `waiting_for_user`나 `failed`로 두고 원문을 `trace.jsonl`에 보존한다.

## 2026-09-09 보강

- `/demo/`: 로컬 정적 실행 기록. `/demo/artifacts/<path>`로 데모 산출물을 조회한다.
- run_id와 새 question_id에 UUID를 붙여 충돌을 막는다. 이전 ID도 조회·답변 가능하다.
- 답변은 서버가 먼저 저장한다. 이미 저장한 ID·version에 같은 답이면 duplicate, 다른 답이면 409다.
- 실행 중 resume은 409다. live는 종료 시 제거되는 실제 실행 컨텍스트 기준이다.
- 필수 산출물·규칙 검사 통과 후 `pending_question.purpose=final_review`가 생성된다. 이 질문에 answer=["최종 승인"]을 제출하면 재검사 후 done, ["수정 필요"]면 halted. SDK 재호출은 없다.
- 재시작으로 끊긴 이미지 승인은 approve(false)로 해제 후 재개할 수 있다. approve(true)는 409다.
- usage의 working_s·waiting_s는 최근 호출의 작업·대기 시간이다. cost_complete는 ResultMessage 수신 여부이며, 조사 비용·전체 재개 누적 집계 완료를 뜻하지 않는다.
- 시간 제한은 작업시간 25분이며 메시지 관찰 시점에 검사한다.
