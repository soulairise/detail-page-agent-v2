# 소울매트 상세페이지 에이전트 V2

Main Quest 4 — 요가용품 상세페이지 제작을 위한 에이전틱 워크플로. Claude Agent SDK로 조사·포지셔닝 질문·스토리보드·카피·규칙 검사·저장을 연결하며 사람이 주요 결정을 확인한다.

**[결과물 웹 미리보기](https://soulairise.github.io/detail-page-agent-v2/) · [PRD](PRD.md) · [평가 결과](EVAL.md) · [API 명세](API_SPEC.md)**

## 실제 상세페이지 JPEG 7장

사용자가 승인한 AI 활용 장면 3장을 사용해 만든 최종 출력물입니다. 각 이미지는 가로 860px이며, 순서대로 연결해 상세페이지에 사용합니다. 원본 JPEG 자체를 아래에 표시했습니다.

**01 · 860 × 1480px**

![상세페이지 01](output/%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88/%EC%B5%9C%EC%A2%85%EC%B6%9C%EB%A0%A5/images/01_%EC%86%8C%EC%9A%B8%EB%A7%A4%ED%8A%B8_%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88_%ED%96%89%EC%82%AC%EC%99%80%EA%B8%B0%EC%97%85%EC%9B%B0%EB%8B%88%EC%8A%A4_%EC%84%9C%EB%B9%84%EC%8A%A4%EC%86%8C%EA%B0%9C%EC%99%80%EA%B2%AC%EC%A0%81%EB%AC%B8%EC%9D%98.jpeg)

**02 · 860 × 2180px**

![상세페이지 02](output/%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88/%EC%B5%9C%EC%A2%85%EC%B6%9C%EB%A0%A5/images/02_%EC%86%8C%EC%9A%B8%EB%A7%A4%ED%8A%B8_%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88_%ED%96%89%EC%82%AC%EC%99%80%EA%B8%B0%EC%97%85%EC%9B%B0%EB%8B%88%EC%8A%A4_%EA%B8%B0%EC%97%85%EC%9B%B0%EB%8B%88%EC%8A%A4%EC%99%80%EC%8A%A4%ED%8A%9C%EB%94%94%EC%98%A4%ED%99%9C%EC%9A%A9.jpeg)

**03 · 860 × 1640px**

![상세페이지 03](output/%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88/%EC%B5%9C%EC%A2%85%EC%B6%9C%EB%A0%A5/images/03_%EC%86%8C%EC%9A%B8%EB%A7%A4%ED%8A%B8_%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88_%ED%96%89%EC%82%AC%EC%99%80%EA%B8%B0%EC%97%85%EC%9B%B0%EB%8B%88%EC%8A%A4_%EB%AC%B8%EC%9D%98%EB%B6%80%ED%84%B0%EB%B0%B0%EC%86%A1%ED%9A%8C%EC%88%98%EA%B9%8C%EC%A7%80.jpeg)

**04 · 860 × 1520px**

![상세페이지 04](output/%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88/%EC%B5%9C%EC%A2%85%EC%B6%9C%EB%A0%A5/images/04_%EC%86%8C%EC%9A%B8%EB%A7%A4%ED%8A%B8_%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88_%ED%96%89%EC%82%AC%EC%99%80%EA%B8%B0%EC%97%85%EC%9B%B0%EB%8B%88%EC%8A%A4_%EB%A7%A4%ED%8A%B8%EC%84%A0%ED%83%9D%EA%B3%BC%EA%B4%80%EB%A6%AC%ED%99%95%EC%9D%B8.jpeg)

**05 · 860 × 1480px**

![상세페이지 05](output/%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88/%EC%B5%9C%EC%A2%85%EC%B6%9C%EB%A0%A5/images/05_%EC%86%8C%EC%9A%B8%EB%A7%A4%ED%8A%B8_%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88_%ED%96%89%EC%82%AC%EC%99%80%EA%B8%B0%EC%97%85%EC%9B%B0%EB%8B%88%EC%8A%A4_%EA%B2%AC%EC%A0%81%ED%95%AD%EB%AA%A9%EA%B3%BC%EB%8C%80%EC%97%AC%EA%B3%84%EC%95%BD%EC%A1%B0%EA%B1%B4.jpeg)

**06 · 860 × 1300px**

![상세페이지 06](output/%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88/%EC%B5%9C%EC%A2%85%EC%B6%9C%EB%A0%A5/images/06_%EC%86%8C%EC%9A%B8%EB%A7%A4%ED%8A%B8_%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88_%ED%96%89%EC%82%AC%EC%99%80%EA%B8%B0%EC%97%85%EC%9B%B0%EB%8B%88%EC%8A%A4_%EC%9E%90%EC%A3%BC%EB%AC%BB%EB%8A%94%EC%A7%88%EB%AC%B8%EA%B3%BC%EC%83%81%EB%8B%B4%EC%95%88%EB%82%B4.jpeg)

**07 · 860 × 1400px**

![상세페이지 07](output/%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88/%EC%B5%9C%EC%A2%85%EC%B6%9C%EB%A0%A5/images/07_%EC%86%8C%EC%9A%B8%EB%A7%A4%ED%8A%B8_%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8%EB%A0%8C%ED%83%88_%ED%96%89%EC%82%AC%EC%99%80%EA%B8%B0%EC%97%85%EC%9B%B0%EB%8B%88%EC%8A%A4_%EC%83%81%ED%92%88%EC%A0%95%EB%B3%B4%EC%99%80%EC%82%AC%EC%9A%A9%EC%A3%BC%EC%9D%98%EC%82%AC%ED%95%AD.jpeg)

실제 HTML 브라우저 캡처는 [screenshots](screenshots)에 보조 자료로 보관했습니다.

## 내려받기

- [카페24 HTML·JPEG 7장 ZIP](output/요가매트렌탈/소울매트_요가매트렌탈_채널별출력.zip)
- [HTML 원본](output/요가매트렌탈/최종출력/소울매트_요가매트렌탈_카페24상세페이지.html)
- [JPEG 파일 목록](output/요가매트렌탈/최종출력/images)
- [파일별 픽셀 크기·내역](output/요가매트렌탈/최종출력/manifest.json)
- [이미지 프롬프트·승인 기록](output/요가매트렌탈/기획)

모든 JPEG는 860px 폭, 주제별 1200~3000px 범위다. 카페24 본문은 이미지와 같은 레이아웃을 유지하는 이미지 기반 HTML이며, 이미지 업로드 후 images/ 경로를 실제 HTTPS URL로 치환한다. 실제 재고 사양·거래조건은 판매 등록 전에 확인해야 한다.

## 실제 에이전트와 평가

도구 7개: search_market, read_playbook, check_compliance, save_artifact, generate_image, ask_user, set_stage. UI에서 질문과 trace, 결과물을 확인한다. 파일 쓰기는 실행 폴더로 제한하며 최종 완료는 실제 파일 검사와 사람 검수 이후다.

기존 Claude 실행 3건은 시간·사용량 제한으로 미완료(0/3)였다. 이후 사용자 이미지 승인과 별도 출력 도구로 완성한 결과물을 엔진 자동 완주로 계산하지 않는다. 로컬 회귀 검증은 18/18 통과했다. [EVAL.md](EVAL.md)에 실패와 변경을 구분해 기록했다.

공개 웹은 **정적 결과물 열람용**이다. 새 상품을 실행하려면 아래 로컬 앱을 사용한다. 공개 URL에서 워크플로를 실행하는 과제 배포 조건은 아직 충족하지 못했다.

## 로컬 실행

Python 3.12+, 로그인된 Claude Code CLI가 필요하다.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.server
```

http://127.0.0.1:8765 접속. 이미지 API 키는 환경변수 또는 app/.env로 설정하고 커밋하지 않는다. 실제 이미지 생성은 별도 Image API 경로이며 앱 도구는 승인 인터페이스까지만 연결돼 있다.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

출력 도구 tools/export_detail.py는 현재 macOS AppleSDGothicNeo 폰트를 사용한다. 다른 OS에서는 사용 가능한 한글 폰트 경로로 바꿔야 한다.

## 공개 범위

공개용 플레이북은 규칙 요약본이다. API 키·원본 실행 세션·개인 메모·공급처·매입단가·원본 대화는 포함하지 않는다.
