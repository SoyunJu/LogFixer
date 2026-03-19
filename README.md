# LogFixer — AI Agent 기반 장애 자동 해결 시스템

> **장애 탐지부터 원인 분석, 서버 조치, 결과 보고까지 전 과정을 자동화한 AI Agent 시스템**
> LogCollector(LC)와 연동하여 운영 중 발생하는 인프라 장애를 사람의 개입 없이 탐지·분석·해결하고,
> 담당자 승인이 필요한 지점에만 Slack으로 Human-in-the-Loop을 구현했습니다.

---

## 핵심 구현 포인트

| | |
|---|---|
| **LLM + RAG 기반 자동 분석** | Elasticsearch BM25와 Qdrant kNN을 RRF로 융합하는 하이브리드 검색으로 관련 KB를 수집하고, GPT-4o-mini가 근본 원인과 해결법 후보를 JSON으로 반환 |
| **Human-in-the-Loop 설계** | 분석 결과와 RESOLVED 확정, 총 2단계에서만 Slack 버튼 승인을 받고 나머지는 완전 자동 처리 |
| **SSH Agent 자동 실행** | 승인 후 대상 서버에 SSH로 접속해 액션을 순차 실행. 실패 시 성공한 액션을 역순 롤백하고 최대 3회 재시도 |
| **상태머신 기반 신뢰성** | 7단계 IncidentState로 전이 규칙을 코드로 강제. 비정상 전이는 예외로 차단 |
| **자기 학습 루프** | 해결 완료된 분석·조치 이력을 LC의 KbArticle addendum으로 저장 → 다음 유사 장애 시 RAG 검색에 자동 활용 |

---

## 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                          LogFixer                                   │
│                                                                     │
│  Webhook        Analyzer              Agent               Reporter  │
│  ─────────      ──────────────────    ─────────────────   ──────── │
│  POST           ES BM25 검색          SSH 접속            LC PATCH  │
│  /api/incident  Qdrant kNN 검색  →   액션 순차 실행   →  LC GET     │
│       ↓         RRF 재랭킹            실패 시 역순 롤백   LC POST    │
│  DB 저장        GPT-4o-mini 분석      재시도 (max 3)                │
│  상태 전이      해결법 순위 생성                                     │
│                      ↓                                              │
│                 Slack 승인 요청 ──────→ 담당자 승인/거절            │
│                                                                     │
│  Scheduler: EXECUTING 감시(30s) / 고빈도 재발 감지(5m)             │
└─────────────────────────────────────────────────────────────────────┘
         ↑ webhook                              ↓ REST API
┌─────────────────┐                   ┌─────────────────────┐
│  LogCollector   │                   │  대상 서버 (SSH)    │
│  (장애 감지)    │                   │  systemctl / sed    │
└─────────────────┘                   └─────────────────────┘
```

---

## 전체 처리 흐름

```
[LC] 장애 감지
      │ POST /api/incident
      ▼
① RECEIVED     ── DB upsert (재발이면 RESOLVED → RECEIVED 재오픈)
      │
      ▼
② ANALYZING    ── ES BM25 + Qdrant kNN → RRF 재랭킹
               ── GPT-4o-mini: root_cause + confidence
               ── GPT-4o-mini: solutions ranking
      │
      ▼
③ PENDING_APPROVAL ── Slack 승인 요청 발송
      │                  [✅ 승인] → EXECUTING
      │                  [❌ 재분석] → RECEIVED
      ▼ (승인)
④ EXECUTING    ── SSH 액션 순차 실행
               ──   RESTART      : systemctl restart <service>
               ──   EDIT_CONFIG  : sed -i (변경 전 값 백업)
               ──   CLEAR_MEMORY : drop_caches
               ──   DEL_DISK     : 14일 이상 .log 삭제
      │
      ├─[성공]─ Slack 해결 보고 발송 → 담당자 [✅ RESOLVED 승인]
      │                                        │
      │                                        ▼
      │                              ⑤ RESOLVED
      │                                        │
      │                               LC PATCH 상태 변경
      │                               LC GET  kbArticleId
      │                               LC POST addendum 저장
      │
      └─[실패]─ ⑥ ROLLING_BACK ── 역순 롤백 실행
                      │
                      ├─ retry < 3  → ① RECEIVED (재분석 재시도)
                      └─ retry ≥ 3  → ⑦ ESCALATED (수동 대응)
```

---

## 상태머신 (IncidentState)

전이 규칙을 `ALLOWED_TRANSITIONS` 딕셔너리로 코드에 명시하고, 허용되지 않은 전이는 즉시 예외를 발생시켜 잘못된 상태 변경을 원천 차단합니다.

```
RECEIVED → ANALYZING → PENDING_APPROVAL ─(재분석)→ RECEIVED
                              │
                          (승인)↓
                          EXECUTING ─(성공)→ RESOLVED
                              │
                           (실패)↓
                          ROLLING_BACK ─(retry < 3)→ RECEIVED
                                       ─(retry ≥ 3)→ ESCALATED
```

| 상태 | 의미 |
|---|---|
| `RECEIVED` | 장애 수신 완료. 분석 대기 |
| `ANALYZING` | LLM + RAG 분석 중 |
| `PENDING_APPROVAL` | Slack 승인 대기 중 |
| `EXECUTING` | SSH Agent 액션 실행 중 |
| `ROLLING_BACK` | 실패 액션 역순 롤백 중 |
| `RESOLVED` | 해결 완료 (담당자 최종 승인) |
| `ESCALATED` | 자동 해결 불가 — 수동 대응 필요 |

---

## RAG 파이프라인 상세

단순 벡터 검색이 아니라 **키워드 검색 + 의미 검색을 RRF로 융합**하여 검색 품질을 높였습니다.

```
신규 incident (summary + stackTrace)
         │
    ┌────┴────┐
    │         │
    ▼         ▼
ES BM25    Qdrant kNN
키워드 검색  벡터 유사도 검색
    │      (kb_articles + error_patterns)
    └────┬────┘
         ▼
    RRF 재랭킹
    (Reciprocal Rank Fusion — 두 랭킹을 순위 역수 합산으로 통합)
         │
         ▼
    상위 k개 문서 → LLM 프롬프트에 컨텍스트로 주입
         │
         ├── GPT-4o-mini: 근본 원인(root_cause) + 신뢰도(confidence) 생성
         └── GPT-4o-mini: 해결법 후보(solutions) 순위 생성
```

### Qdrant 컬렉션 구성

| 컬렉션 | 저장 내용 | 활용 |
|---|---|---|
| `kb_articles` | KbArticle 본문 + 해결 addendum | 유사 과거 사례 검색 |
| `error_patterns` | stacktrace 요약, 에러 타입 | 유사 에러 패턴 매칭 |
| `solutions` | 검증된 해결법 (성공 횟수 포함) | 해결법 우선순위 보정 |

> 해결 완료 후 이력이 addendum으로 `kb_articles`에 쌓이므로, 시스템이 운영될수록 **검색 품질이 자동으로 향상**됩니다.

---

## Slack Human-in-the-Loop

### 1단계 — 분석 완료, 실행 승인 요청

```
┌──────────────────────────────────────────────────┐
│  [LogFixer] 장애 분석 완료 | 승인 요청            │
├──────────────────────────────────────────────────┤
│  서비스: prod-api                                 │
│  원인:   메모리 누수 — Java heap 용량 부족         │
│  신뢰도: 87%                                      │
│  해결법:                                          │
│    1. [RESTART]     prod-api 재시작               │
│    2. [EDIT_CONFIG] heap 설정 2G → 4G             │
│  근거:   KbArticle #42, #17                       │
├──────────────────────────────────────────────────┤
│        [✅ 승인]          [❌ 재분석]              │
└──────────────────────────────────────────────────┘
```

### 2단계 — 실행 완료, RESOLVED 확정 요청 (스레드 답글)

```
┌──────────────────────────────────────────────────┐
│  [LogFixer] AI Agent 장애 해결 보고               │
├──────────────────────────────────────────────────┤
│  서비스:    prod-api                              │
│  소요 시간: 3분                                   │
│  실행 내역:                                       │
│    - RESTART: prod-api 재시작 완료 ✅              │
│    - EDIT_CONFIG: heap=4g 변경 완료 ✅             │
├──────────────────────────────────────────────────┤
│              [✅ RESOLVED 승인]                   │
└──────────────────────────────────────────────────┘
```

---

## Agent 액션 목록

| 액션 | 실행 내용 | 롤백 |
|---|---|---|
| `RESTART` | `sudo systemctl restart <service>` | ✅ 동일 명령으로 복구 |
| `EDIT_CONFIG` | `sed -i`로 설정 키/값 변경 (변경 전 값 백업) | ✅ 원래 값으로 되돌림 |
| `CLEAR_MEMORY` | `echo 3 > /proc/sys/vm/drop_caches` | ❌ 비가역적 |
| `DEL_DISK` | 14일 이상 된 `.log` 파일 삭제 | ❌ 비가역적 |

액션 실패 시 그 시점까지 성공한 액션들을 **역순으로 롤백**한 뒤, 최대 3회까지 RECEIVED 상태로 돌아가 재분석·재실행을 시도합니다.

---

## LC ↔ LogFixer 연동

해결 완료 후 LC API를 **순서대로** 호출합니다. kbArticleId 조회는 LC 측 생성 시간이 필요하므로 최대 5회 retry(3초 간격)를 적용했습니다.

```
1. PATCH /api/incidents/{logHash}/status    상태 → RESOLVED
2. GET   /api/kb/articles/byhash/{logHash}  kbArticleId 조회 (retry × 5)
3. POST  /api/kb/{kbArticleId}/addendums    분석 결과 + 실행 내역 저장
```

---

## 기술 스택

| 분류 | 기술 / 버전 |
|---|---|
| **Backend** | Python 3.12, FastAPI 0.115, Uvicorn |
| **AI / LLM** | OpenAI GPT-4o-mini, RAG (BM25 + kNN + RRF) |
| **Vector DB** | Qdrant 1.12 |
| **Search** | Elasticsearch 8.15 |
| **RDB** | MariaDB 11.4, SQLAlchemy 2.0 (async), aiomysql |
| **Scheduler** | APScheduler 3.10 |
| **Notification** | Slack SDK 3.33 (Interactive Actions) |
| **SSH** | Paramiko 3.5 |
| **HTTP Client** | httpx 0.27 |
| **Infra** | Docker Compose |

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/health` | 헬스 체크 |
| `POST` | `/api/incident` | LC webhook 수신 — RECEIVED 저장 (202) |
| `GET` | `/api/incident/{log_hash}` | Incident 상태 조회 |
| `POST` | `/api/incident/{log_hash}/analyze` | 분석 수동 트리거 (dev/test) |
| `POST` | `/api/incident/{log_hash}/execute` | 실행 수동 트리거 (dev/test) |
| `POST` | `/api/incident/{log_hash}/resolve` | RESOLVED 처리 + LC 보고 |
| `POST` | `/api/slack/actions` | Slack 버튼 액션 수신 |

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

## 환경변수 설정 (.env)

| 변수 | 설명 |
|---|---|
| `OPENAI_API_KEY` | GPT-4o-mini 호출용 OpenAI API 키 |
| `SLACK_BOT_TOKEN` | Slack Bot OAuth 토큰 (`xoxb-...`) |
| `SLACK_CHANNEL_ID` | 알림을 보낼 Slack 채널 ID |
| `LC_BASE_URL` | LogCollector 서버 주소 |
| `DB_HOST / DB_NAME / DB_USER / DB_PASSWORD` | MariaDB 접속 정보 |
| `QDRANT_HOST / QDRANT_PORT` | Qdrant 접속 정보 |
| `ES_HOST` | Elasticsearch 주소 |
| `SSH_DEFAULT_USER / SSH_DEFAULT_KEY_PATH` | SSH 접속 계정 및 개인키 경로 |

---

## 프로젝트 구조

```
LogFixer/
├── app/
│   ├── main.py                    # FastAPI 앱, lifespan (DB·Qdrant 초기화, Scheduler 시작)
│   ├── api/
│   │   ├── incident.py            # webhook 수신, 분석/실행/해결 엔드포인트
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
│   │   ├── retriever.py           # BM25 + kNN → RRF 통합 검색
│   │   ├── embedder.py            # OpenAI Embedding 호출
│   │   └── kb_search.py           # Elasticsearch BM25 검색
│   ├── vectordb/
│   │   ├── client.py              # Qdrant AsyncClient
│   │   └── store.py               # 컬렉션 초기화, 벡터 upsert
│   ├── notification/
│   │   └── slack.py               # 승인 요청 / 해결 보고 Block Kit 메시지
│   ├── reporter/
│   │   ├── kb_updater.py          # LC API 순차 호출 (PATCH → GET → POST)
│   │   └── generator.py           # addendum 텍스트 생성
│   ├── scheduler/
│   │   └── poller.py              # EXECUTING 감시(30s), 고빈도 재발 감지(5m)
│   ├── status/
│   │   └── machine.py             # 상태머신 — upsert / transition / 전이 규칙 강제
│   ├── db/
│   │   ├── session.py             # AsyncSession 팩토리
│   │   └── models.py              # LfIncident SQLAlchemy 모델
│   ├── schemas/                   # Pydantic 요청·응답·분석 결과 스키마
│   └── core/                      # config / enums / exceptions / dependencies
├── docker/
│   └── docker-compose.yml         # MariaDB + Qdrant + Elasticsearch
├── docs/
│   └── architecture.md            # 상세 아키텍처 문서
├── tests/
│   ├── unit/
│   └── integration/
├── requirements.txt
└── .env.example
```
