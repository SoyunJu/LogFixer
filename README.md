# LogFixer — AI Agent 기반 장애 자동 해결 시스템

> **장애 탐지부터 원인 분석, 서버 조치, 결과 보고까지 전 과정을 자동화한 AI Agent 백엔드 시스템**

LogCollector(LC)와 연동하여 운영 중 발생하는 인프라 장애를 자동으로 탐지·분석·조치하고,  
꼭 필요한 두 지점에서만 담당자의 Slack 승인을 받는 **Human-in-the-Loop** 구조로 설계했습니다.

비전공·운영 출신으로서 반복적인 수동 장애 대응 경험을 바탕으로,  
"이 과정이 자동화될 수 있지 않을까?"라는 질문에서 시작한 프로젝트입니다.

---

## 핵심 구현 포인트

| 항목 | 내용 |
|---|---|
| **LLM + RAG 기반 자동 분석** | Elasticsearch BM25와 Qdrant kNN을 RRF로 융합하는 하이브리드 검색으로 관련 KB를 수집하고, GPT-4o-mini가 근본 원인과 해결법 후보를 JSON으로 반환 |
| **Human-in-the-Loop 설계** | 분석 결과 승인·RESOLVED 확정, 총 2단계에서만 Slack 버튼 승인을 받고 나머지는 완전 자동 처리 |
| **SSH Agent 자동 실행** | 승인 후 대상 서버에 SSH로 접속해 액션을 순차 실행. 실패 시 성공한 액션을 역순 롤백하고 최대 3회 재시도 |
| **상태머신 기반 신뢰성** | 7단계 IncidentState로 전이 규칙을 코드로 강제. 허용되지 않은 전이는 즉시 예외로 차단 |
| **자기 학습 루프** | 해결 완료된 분석·조치 이력을 LC의 KbArticle addendum으로 저장 → 다음 유사 장애 RAG 검색에 자동 활용 |

---

## 기술 스택

| 분류 | 기술 |
|---|---|
| **Backend** | Python 3.11, FastAPI, Uvicorn |
| **AI / LLM** | OpenAI GPT-4o-mini, text-embedding-3-small |
| **RAG** | Elasticsearch 8 (BM25) + Qdrant (kNN) + RRF 재랭킹 |
| **DB** | MariaDB 11, SQLAlchemy 2.0 (async), aiomysql |
| **Scheduler** | APScheduler 3.10 |
| **Notification** | Slack SDK (Interactive Actions) |
| **SSH** | Paramiko |
| **Infra** | Docker Compose |

---

## 시스템 아키텍처

```
┌──────────────────────────────────────────────────────────────────┐
│                           LogFixer                               │
│                                                                  │
│  Webhook        Analyzer                Agent           Reporter │
│  ──────────     ─────────────────────   ──────────────  ─────── │
│  POST           ES BM25 검색            SSH 접속         LC PATCH│
│  /api/incident  Qdrant kNN 검색    →   액션 순차 실행  → LC GET  │
│       ↓         RRF 재랭킹              실패 시 역순 롤백  LC POST│
│  DB 저장        GPT-4o-mini 분석        재시도 (max 3)           │
│  상태 전이      해결법 순위 생성                                  │
│                      ↓                                           │
│              Slack 승인 요청 ────────→ 담당자 승인 / 재분석      │
│                                                                  │
│  Scheduler: EXECUTING 상태 감시(30s) / 고빈도 재발 감지(5m)     │
└──────────────────────────────────────────────────────────────────┘
         ↑ webhook push                      ↓ REST API 호출
┌─────────────────┐                ┌──────────────────────────┐
│  LogCollector   │                │  대상 서버 (SSH)         │
│  (장애 감지·    │                │  systemctl / sed /       │
│   KB 관리)      │                │  drop_caches / rm        │
└─────────────────┘                └──────────────────────────┘
```

---

## 전체 처리 흐름

```
[LogCollector] 장애 감지
      │ POST /api/incident (webhook)
      ▼
① RECEIVED       ── DB upsert / 재발이면 RESOLVED → RECEIVED 재오픈
      │
      ▼
② ANALYZING      ── ES BM25 + Qdrant kNN → RRF 재랭킹
                 ── GPT-4o-mini ① root_cause + confidence 분석
                 ── GPT-4o-mini ② solutions ranking 생성
      │
      ▼
③ PENDING_APPROVAL ── Slack 승인 요청 발송
      │                   [✅ 승인] → EXECUTING
      │                   [❌ 재분석] → RECEIVED
      ▼ (승인)
④ EXECUTING      ── SSH 액션 순차 실행
                 ──   RESTART      : systemctl restart <service>
                 ──   EDIT_CONFIG  : sed -i  (변경 전 값 백업)
                 ──   CLEAR_MEMORY : drop_caches
                 ──   DEL_DISK     : 14일 이상 .log 삭제
      │
      ├─[성공]─ Slack 실행 완료 보고 발송
      │              └─ 담당자 [✅ RESOLVED 승인]
      │                        ▼
      │                ⑤ RESOLVED
      │                   ├─ LC PATCH 상태 변경
      │                   ├─ LC GET  kbArticleId (최대 5회 retry)
      │                   └─ LC POST addendum 저장 (분석 결과 + 실행 이력)
      │
      └─[실패]─ ⑥ ROLLING_BACK ── 성공한 액션 역순 롤백
                      │
                      ├─ retry < 3  → ① RECEIVED (재분석·재시도)
                      └─ retry ≥ 3  → ⑦ ESCALATED (수동 대응 전환)
```

---

## 증적 (실제 동작 화면)

### 1. LC → LogFixer 웹훅 수신

LogCollector가 장애를 감지하면 LogFixer의 `/api/incident` 엔드포인트로 웹훅을 전송합니다.  
수신 즉시 DB에 저장하고 `RECEIVED` 상태로 응답합니다.

<!-- 이미지 삽입 위치 -->
<!-- 파일명: LC_LF_로그처리받기.png -->
<!-- 설명: PowerShell에서 웹훅 POST 전송 → logHash=flow001 RECEIVED 응답 확인 -->
```
[IMAGE: LC_LF_로그처리받기.png]
PowerShell 웹훅 전송 → RECEIVED 상태 저장 확인
```

<!-- 파일명: LC_LF_로그처리받기_2.png -->
<!-- 설명: GET /api/incident/flow001 조회 결과 — id, state, retry_count 등 전체 필드 확인 -->
```
[IMAGE: LC_LF_로그처리받기_2.png]
GET 조회: state=RECEIVED, retry_count=0 등 DB 저장 상태 확인
```

---

### 2. RAG + LLM 자동 분석

웹훅 수신 후 ES BM25 + Qdrant kNN으로 유사 KB를 검색하고,  
RRF 재랭킹 결과를 컨텍스트로 GPT-4o-mini 2-step 분석을 실행합니다.  
분석 완료 시 `PENDING_APPROVAL` 상태로 전이하고 Slack 승인 요청을 발송합니다.

<!-- 이미지 삽입 위치 -->
<!-- 파일명: RAG_AI분석.png -->
<!-- 설명: 터미널 로그 — BM25/kNN 검색 → RRF → LLM 2-step 분석 → PENDING_APPROVAL 전이 → Slack 알림 발송 전 과정 로그 -->
```
[IMAGE: RAG_AI분석.png]
RAG 검색 → GPT-4o-mini 분석 → PENDING_APPROVAL 전이 → Slack 발송 전체 로그
```

---

### 3. Slack 장애 분석 결과 알림 (승인 요청)

분석이 완료되면 서비스명·원인·신뢰도·해결법 후보를 Slack으로 전송합니다.  
담당자는 `[✅ 승인]` 또는 `[❌ 재분석]` 버튼으로 응답합니다.

<!-- 이미지 삽입 위치 -->
<!-- 파일명: 슬랙—승인요청알림.png  (풀스크린 슬랙 화면) -->
<!-- 설명: Slack #error_manager 채널 — "[LogFixer] 장애 분석 완료 | 승인 요청" 메시지, 서비스/원인/신뢰도85%/해결법 3개 표시, ✅ 승인 / ❌ 재분석 버튼 -->
```
[IMAGE: 슬랙—승인요청알림.png]
Slack 알림: 서비스·원인·신뢰도·해결법 후보 + 승인/재분석 버튼
```

<!-- (선택) 파일명: LF분석_슬랙알림.png -->
<!-- 설명: PowerShell 분석 API 응답(rootCause, confidence, solutions)과 슬랙 알림 화면을 함께 보여줌 -->
```
[IMAGE: LF분석_슬랙알림.png]  ← 선택적 추가 (API 응답과 슬랙 알림 동시 확인)
analyze API 응답값 + Slack 알림 화면
```

---

### 4. Slack 승인 → 상태 전이

담당자가 `[✅ 승인]` 버튼을 누르면 `/api/slack/actions` 엔드포인트가 호출되고  
`PENDING_APPROVAL → EXECUTING` 상태 전이가 이루어집니다.

<!-- 이미지 삽입 위치 -->
<!-- 파일명: 슬랙승인시_state전이.png -->
<!-- 설명: PowerShell approve payload 전송 → 터미널 로그에서 "[Slack] 승인 완료 logHash=flow001 user=테스트유저" 확인 -->
```
[IMAGE: 슬랙승인시_state전이.png]
Slack 승인 액션 수신 → PENDING_APPROVAL → EXECUTING 전이 로그
```

---

### 5. 해결 완료 → LC에 결과 보고 (resolve)

실행 성공 후 담당자 승인을 통해 `RESOLVED` 처리를 하면,  
LC에 순서대로 상태 변경 → kbArticleId 조회 → addendum 저장을 호출합니다.

<!-- 이미지 삽입 위치 -->
<!-- 파일명: LF_resolve처리_전.png -->
<!-- 설명: Swagger UI에서 /api/incident/{log_hash}/resolve 실행 전 — LC 화면에서 해당 incident가 IN_PROGRESS 상태 -->
```
[IMAGE: LF_resolve처리_전.png]
resolve 호출 전: LC 화면에서 incident 상태 IN_PROGRESS
```

<!-- 파일명: LF_resolve처리_후.png -->
<!-- 설명: resolve POST 실행 후 — 응답 body에 state: RESOLVED, lcReported: true / LC 화면에서 RESOLVED로 변경 확인 -->
```
[IMAGE: LF_resolve처리_후.png]
resolve 처리 후: LC 상태 RESOLVED 반영 확인 (lcReported: true)
```

---

### 6. 해결 실패 시 — 자동 롤백

SSH 실행이 실패하면 `ROLLING_BACK` 상태로 전이하고, 성공했던 액션들을 역순으로 롤백합니다.  
`retry_count < 3`이면 `RECEIVED`로 복귀해 재분석을 재시도합니다.

<!-- 이미지 삽입 위치 -->
<!-- 파일명: 해결실패시_롤백.png -->
<!-- 설명: 존재하지 않는 호스트(999.999.999.999)로 실행 시도 → SSH 접속 실패 → ROLLING_BACK 전이 로그 -->
```
[IMAGE: 해결실패시_롤백.png]
SSH 실패 감지 → ROLLING_BACK 상태 전이
```

<!-- 파일명: 롤백처리.png + 롤백처리_2.png -->
<!-- 설명: 롤백 실행 로그 (ROLLING_BACK → RECEIVED 전이) + 롤백 완료 후 retry=1 카운트 -->
```
[IMAGE: 롤백처리.png]
롤백 실행 로그: ROLLING_BACK → RECEIVED 재오픈

[IMAGE: 롤백처리_2.png]
롤백 완료: retry=1 증가, RECEIVED 상태로 재시도 대기
```

---

### 7. 재발 감지 → 자동 재오픈

이미 `RESOLVED` 처리된 장애와 동일한 `logHash`로 웹훅이 재수신되면,  
`RESOLVED → RECEIVED` 상태 전이와 함께 retry_count를 초기화하고 재분석을 시작합니다.

<!-- 이미지 삽입 위치 -->
<!-- 파일명: 재발_state전이.png -->
<!-- 설명: 동일 logHash (flow001)로 재발 웹훅 전송 → state=RECEIVED로 재오픈, repeatCount=8로 갱신 -->
```
[IMAGE: 재발_state전이.png]
동일 logHash 재수신 → RESOLVED → RECEIVED 재오픈, repeatCount 갱신
```

---

### 8. KB Addendum 자동 작성

`RESOLVED` 처리 완료 후 LC의 KbArticle에 분석 결과·실행 내역·해결 시각이 자동으로 기록됩니다.  
이 데이터는 다음 유사 장애 발생 시 RAG 검색 컨텍스트로 활용됩니다.

<!-- 이미지 삽입 위치 -->
<!-- 파일명: kb_addenum_자동_작성.png -->
<!-- 설명: LC의 KB Article 상세 화면 — "Resolution Notes & Updates" 섹션에 LogFixer Agent가 자동 작성한 분석 결과/실행 내역/신뢰도 기재 -->
```
[IMAGE: kb_addenum_자동_작성.png]
LC KB Article에 LogFixer가 자동 작성한 분석 결과 + 실행 이력 addendum
```

---

## 상태머신 (IncidentState)

전이 규칙을 `ALLOWED_TRANSITIONS` 딕셔너리로 코드에 명시하고,  
허용되지 않은 전이 시도는 즉시 예외를 발생시켜 잘못된 상태 변경을 원천 차단합니다.

```
RECEIVED
   │
   ▼
ANALYZING
   │
   ▼
PENDING_APPROVAL ──(재분석 요청)──→ RECEIVED
   │
   ▼ (담당자 승인)
EXECUTING
   │
   ├──(성공)──→ RESOLVED ──→ LC 상태 변경 + addendum 저장
   │
   └──(실패)──→ ROLLING_BACK
                    │
                    ├──(retry < 3)──→ RECEIVED (재시도)
                    │
                    └──(retry ≥ 3)──→ ESCALATED (수동 대응)
```

```python
# app/status/machine.py
ALLOWED_TRANSITIONS: dict[IncidentState, list[IncidentState]] = {
    IncidentState.RECEIVED:         [IncidentState.ANALYZING],
    IncidentState.ANALYZING:        [IncidentState.PENDING_APPROVAL],
    IncidentState.PENDING_APPROVAL: [IncidentState.EXECUTING, IncidentState.RECEIVED],
    IncidentState.EXECUTING:        [IncidentState.RESOLVED, IncidentState.ROLLING_BACK],
    IncidentState.ROLLING_BACK:     [IncidentState.RECEIVED, IncidentState.ESCALATED],
    IncidentState.RESOLVED:         [],
    IncidentState.ESCALATED:        [],
}
```

---

## LC ↔ LogFixer 연동

| 방향 | 방식 | 설명 |
|---|---|---|
| LC → LogFixer | Webhook push | 장애 발생 시 `POST /api/incident`로 실시간 전달 |
| LogFixer → LC | REST API 호출 | 해결 완료 후 순차 호출 |

해결 완료 후 LC API를 아래 순서로 호출합니다.  
kbArticleId 조회는 LC 측 생성 시간이 필요하므로 **최대 5회 retry (3초 간격)** 를 적용했습니다.

```
1. PATCH /api/incidents/{logHash}/status    →  상태 → RESOLVED
2. GET   /api/kb/articles/by-hash/{logHash} →  kbArticleId 조회 (retry × 5)
3. POST  /api/kb/{kbArticleId}/addendums    →  분석 결과 + 실행 이력 저장
```

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/health` | 헬스 체크 |
| `POST` | `/api/incident` | LC 웹훅 수신 — RECEIVED 저장 |
| `GET` | `/api/incident/{log_hash}` | Incident 상태 조회 |
| `POST` | `/api/incident/{log_hash}/analyze` | 분석 수동 트리거 (dev/test) |
| `POST` | `/api/incident/{log_hash}/execute` | 실행 수동 트리거 (dev/test) |
| `POST` | `/api/incident/{log_hash}/resolve` | RESOLVED 처리 + LC 보고 |
| `POST` | `/api/slack/actions` | Slack 버튼 액션 수신 |

---

## 프로젝트 구조

```
LogFixer/
├── app/
│   ├── main.py                    # FastAPI 앱, lifespan (DB·Qdrant 초기화, Scheduler 시작)
│   ├── api/
│   │   ├── incident.py            # 웹훅 수신, 분석/실행/해결 엔드포인트
│   │   └── slack_action.py        # Slack Interactive Action (승인·재분석·resolve 버튼)
│   ├── analyzer/
│   │   ├── llm_analyzer.py        # RAG 검색 → GPT-4o-mini 2-step 분석 메인 로직
│   │   ├── validator.py           # 분석 결과 신뢰도·완결성 검증
│   │   └── prompts/               # root_cause / solution_rank 프롬프트 빌더
│   ├── agent/
│   │   ├── ssh_executor.py        # Paramiko 기반 SSH 명령 실행
│   │   ├── action_registry.py     # action_type → Action 클래스 매핑
│   │   ├── rollback.py            # 역순 롤백 실행
│   │   └── actions/               # RESTART / EDIT_CONFIG / CLEAR_MEMORY / DEL_DISK
│   ├── rag/
│   │   └── retriever.py           # ES BM25 + Qdrant kNN → RRF 재랭킹
│   ├── vectordb/
│   │   ├── store.py               # Qdrant 컬렉션 upsert
│   │   └── embedder.py            # text-embedding-3-small 임베딩
│   ├── reporter/
│   │   └── kb_updater.py          # LC PATCH / GET / POST 순차 호출
│   ├── notification/
│   │   └── slack.py               # Slack 메시지 빌더 + 발송
│   ├── scheduler/
│   │   └── jobs.py                # APScheduler: 실행 감시(30s) / 재발 감지(5m)
│   ├── status/
│   │   └── machine.py             # 상태머신 + upsert_incident
│   ├── db/
│   │   ├── models.py              # SQLAlchemy ORM (LfIncident)
│   │   └── session.py             # async 세션 팩토리
│   └── core/
│       ├── config.py              # 환경변수 로드
│       ├── enums.py               # IncidentState
│       └── exceptions.py          # 커스텀 예외
└── docker/
    └── docker-compose.yml         # MariaDB / Qdrant / Elasticsearch
```

---

## 실행 방법

**인프라 실행** (MariaDB · Qdrant · Elasticsearch)

```bash
cd docker && docker compose up -d
```

**애플리케이션 실행**

```bash
cp .env.example .env    # API 키 등 환경변수 설정
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**헬스 체크**

```bash
curl http://localhost:8000/health
# {"status": "ok", "env": "development"}
```

---

## 환경변수 (.env)

| 변수 | 설명 |
|---|---|
| `OPENAI_API_KEY` | GPT-4o-mini / text-embedding-3-small 호출용 키 |
| `SLACK_BOT_TOKEN` | Slack Bot OAuth 토큰 (`xoxb-...`) |
| `SLACK_CHANNEL_ID` | 알림을 보낼 Slack 채널 ID |
| `LC_BASE_URL` | LogCollector 서버 주소 |
| `DB_HOST / DB_NAME / DB_USER / DB_PASSWORD` | MariaDB 접속 정보 |
| `QDRANT_HOST / QDRANT_PORT` | Qdrant 접속 정보 |
| `ES_HOST` | Elasticsearch 주소 |
| `SSH_DEFAULT_USER / SSH_DEFAULT_KEY_PATH` | SSH 접속 계정 및 개인키 경로 |