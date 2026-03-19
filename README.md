# LogFixer

**LogCollector(LC)** 와 연동하여 장애 발생 시 자동으로 원인을 분석하고, 담당자의 Slack 승인을 거쳐 AI Agent가 직접 해결을 실행하는 자동화 시스템입니다.

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [전체 처리 흐름](#2-전체-처리-흐름)
3. [상태머신 (IncidentState)](#3-상태머신-incidentstate)
4. [주요 기능](#4-주요-기능)
5. [Slack 알림 흐름](#5-slack-알림-흐름)
6. [LC ↔ LogFixer 연동](#6-lc--logfixer-연동)
7. [RAG 검색 전략](#7-rag-검색-전략)
8. [Agent 액션 목록](#8-agent-액션-목록)
9. [기술 스택](#9-기술-스택)
10. [API 엔드포인트](#10-api-엔드포인트)
11. [환경 설정](#11-환경-설정)
12. [실행 방법](#12-실행-방법)
13. [프로젝트 구조](#13-프로젝트-구조)

---

## 1. 시스템 개요

```
LogCollector (LC)
      │
      │  POST /api/incident  (webhook push)
      ▼
  LogFixer
      │
      ├── LLM 분석 (GPT-4o-mini + RAG)
      │
      ├── Slack 승인 요청 → 담당자 승인/거절
      │
      ├── SSH Agent 자동 실행 (재시작 / 설정 변경 / 메모리·디스크 정리)
      │
      ├── 실패 시 자동 롤백 + 재시도 (최대 3회)
      │
      └── 해결 완료 → LC 상태 변경 + KB addendum 저장
```

LogFixer는 다음 세 가지 핵심 역할을 수행합니다.

| 역할 | 설명 |
|---|---|
| **자동 분석** | RAG(Qdrant + ES 하이브리드) + GPT-4o-mini로 원인 파악 및 해결법 순위 선정 |
| **자동 실행** | 담당자 Slack 승인 후 SSH를 통해 대상 서버에 직접 조치 수행 |
| **자동 보고** | 해결 결과를 Slack으로 보고하고, LC의 KbArticle에 addendum으로 기록 |

---

## 2. 전체 처리 흐름

```
[LC] 장애 감지
      │
      │ POST /api/incident (webhook)
      ▼
[LogFixer] RECEIVED 상태로 저장
      │
      ▼
[LogFixer] ANALYZING
      │  RAG 검색 (Qdrant kNN + ES BM25 → RRF 재랭킹)
      │  LLM 원인 분석 (root cause + confidence)
      │  LLM 해결법 순위 선정 (solutions ranking)
      ▼
[LogFixer] PENDING_APPROVAL
      │  Slack 승인 요청 발송
      │  [✅ 승인] / [❌ 재분석]
      ▼
(담당자 승인)
      │
      ▼
[LogFixer] EXECUTING
      │  SSH Agent 액션 순차 실행
      │    - RESTART         : systemctl restart <service>
      │    - EDIT_CONFIG     : 설정 파일 키/값 변경 (롤백 명령 백업)
      │    - CLEAR_MEMORY    : drop_caches
      │    - DEL_DISK        : 14일 이상 로그 파일 삭제
      ▼
(성공)─────────────────────────────────────────────┐
      │                                             │
(실패)                                             ▼
      ▼                                    [LogFixer] EXECUTING 유지
[LogFixer] ROLLING_BACK                    Slack 해결 보고 발송
      │  역순 롤백 명령 실행               [✅ RESOLVED 승인] 버튼
      │                                             │
      ├── retry < 3 → RECEIVED (재시도)             │ (담당자 RESOLVED 승인)
      │                                             ▼
      └── retry ≥ 3 → ESCALATED             [LogFixer] RESOLVED
                                                    │
                                                    ▼
                                           [LC] 상태 RESOLVED 변경
                                           [LC] KB addendum 저장
```

> **재발 감지**: 이미 RESOLVED된 incident에 LC가 동일 `logHash`로 재전송하면 자동으로 RECEIVED 상태로 재오픈됩니다.

---

## 3. 상태머신 (IncidentState)

```
RECEIVED
   │
   ▼
ANALYZING
   │
   ▼
PENDING_APPROVAL ──(담당자 재분석)──> RECEIVED
   │
   ▼ (담당자 승인)
EXECUTING
   │
   ├──(성공)──────────────────────> RESOLVED (담당자 RESOLVED 승인 후)
   │
   └──(실패)──> ROLLING_BACK
                    │
                    ├──(retry < 3)──> RECEIVED (재시도)
                    │
                    └──(retry ≥ 3 or 롤백 실패)──> ESCALATED
```

| 상태 | 설명 |
|---|---|
| `RECEIVED` | LC로부터 incident 수신 완료 |
| `ANALYZING` | LLM + RAG 분석 중 |
| `PENDING_APPROVAL` | Slack 승인 대기 중 |
| `EXECUTING` | SSH Agent 액션 실행 중 |
| `ROLLING_BACK` | 실패로 인한 롤백 수행 중 |
| `RESOLVED` | 해결 완료 (담당자 최종 승인) |
| `ESCALATED` | 자동 해결 불가 — 수동 대응 필요 |

---

## 4. 주요 기능

### 4-1. 자동 분석 (LLM + RAG)

- Qdrant kNN 벡터 검색과 Elasticsearch BM25 키워드 검색을 **RRF(Reciprocal Rank Fusion)** 로 통합
- 상위 `k`개 문서를 컨텍스트로 주입해 **GPT-4o-mini** 가 근본 원인(root cause)과 신뢰도(confidence) 반환
- 이어서 동일 컨텍스트로 해결법 후보(solutions)를 순위별로 생성

### 4-2. Slack 승인 워크플로우

- 분석 완료 시 지정 채널로 **승인 요청 메시지** 발송 (서비스명 / 원인 / 신뢰도 / 해결법 / 근거 KB)
- 담당자가 `[✅ 승인]` 또는 `[❌ 재분석]` 버튼으로 응답
- 실행 완료 후 동일 스레드에 **해결 보고 메시지** 발송, `[✅ RESOLVED 승인]` 버튼으로 최종 확정

### 4-3. SSH Agent 자동 실행

- 액션 실패 시 성공한 액션들에 대해 **역순 롤백** 자동 수행
- 롤백 후 최대 **3회 재시도**, 초과 시 `ESCALATED` 전이

### 4-4. Scheduler (APScheduler)

| 주기 | 대상 상태 | 동작 |
|---|---|---|
| 30초 | `EXECUTING` | stuck 여부 감지 / 경고 로그 |
| 5분 | `RECEIVED` | `repeat_count ≥ 5` 고빈도 재발 incident 경고 |

### 4-5. KB Addendum 자동 저장

해결 완료 후 LC API를 순차 호출하여 KbArticle에 분석·해결 이력을 기록합니다.

```
1. PATCH /api/incidents/{logHash}/status        → 상태 RESOLVED 변경
2. GET  /api/kb/articles/byhash/{logHash}        → kbArticleId 조회 (최대 5회 retry)
3. POST /api/kb/{kbArticleId}/addendums          → 분석 결과 + 실행 내역 저장
```

---

## 5. Slack 알림 흐름

### 1단계 — 분석 완료 승인 요청

```
┌─────────────────────────────────────────────┐
│  [LogFixer] 장애 분석 완료 | 승인 요청        │
├─────────────────────────────────────────────┤
│  서비스: prod-api                            │
│  원인:   메모리 누수 - Java heap 용량 부족    │
│  신뢰도: 87%                                 │
│  해결법:                                     │
│    1. [RESTART]     prod-api 재시작           │
│    2. [EDIT_CONFIG] heap 설정 2G → 4G        │
│  근거:   KbArticle #42, #17                  │
├─────────────────────────────────────────────┤
│  [✅ 승인]            [❌ 재분석]             │
└─────────────────────────────────────────────┘
```

### 2단계 — 실행 완료 보고 (스레드 답글)

```
┌─────────────────────────────────────────────┐
│  [LogFixer] AI Agent 장애 해결 보고           │
├─────────────────────────────────────────────┤
│  서비스:   prod-api                          │
│  소요시간: 3분                               │
│  실행 내역:                                  │
│    - RESTART: prod-api 재시작 완료 ✅         │
│    - EDIT_CONFIG: heap=4g 설정 변경 완료 ✅   │
├─────────────────────────────────────────────┤
│  [✅ RESOLVED 승인]                          │
└─────────────────────────────────────────────┘
```

---

## 6. LC ↔ LogFixer 연동

| 방향 | 방식 | 설명 |
|---|---|---|
| LC → LogFixer | Webhook push | incident 생성 시 `POST /api/incident` 실시간 전달 |
| LogFixer → LC | REST API 호출 | 해결 완료 후 상태 변경 및 addendum 저장 |
| LogFixer 내부 | Polling (APScheduler) | 실행 감시(30초) 및 재발 감지(5분) |

---

## 7. RAG 검색 전략

```
신규 incident 수신
       │
       ├── [ES BM25 검색]        키워드 기반 KbArticle 검색
       │
       └── [Qdrant kNN 검색]     벡터 유사도 검색
                │                (kb_articles + error_patterns)
                ▼
          [RRF 재랭킹]           두 결과 통합
                │
                ▼
          [LLM 컨텍스트 주입]    상위 k개 문서 → 프롬프트 포함
                │
                ▼
          원인 분석 + 해결법 순위 선정
```

### Qdrant 컬렉션

| 컬렉션 | 저장 데이터 | 용도 |
|---|---|---|
| `kb_articles` | KbArticle + addendum 임베딩 | 유사 KB 문서 검색 |
| `error_patterns` | 과거 에러 패턴 (stacktrace 요약) | 유사 에러 빠른 탐색 |
| `solutions` | 검증된 해결법 | 해결법 우선 참조 |

---

## 8. Agent 액션 목록

| action_type | 실행 명령 | 롤백 가능 여부 |
|---|---|---|
| `RESTART` | `sudo systemctl restart <target>` | ✅ 가능 |
| `EDIT_CONFIG` | `sed -i` 로 설정 파일 키/값 변경 | ✅ 가능 (이전 값 백업) |
| `CLEAR_MEMORY` | `sync && echo 3 > /proc/sys/vm/drop_caches` | ❌ 불가 |
| `DEL_DISK` | `find <target> -name '*.log' -mtime +14 -delete` | ❌ 불가 |

> `CLEAR_MEMORY`, `DEL_DISK` 는 비가역적 액션으로 롤백 명령이 없습니다.

---

## 9. 기술 스택

| 분류 | 기술 |
|---|---|
| **Web Framework** | FastAPI 0.115, Uvicorn |
| **DB** | MariaDB 11.4 (SQLAlchemy 2.0 + aiomysql) |
| **Vector DB** | Qdrant 1.12 |
| **Search** | Elasticsearch 8.15 |
| **LLM** | OpenAI GPT-4o-mini (openai 1.51) |
| **Scheduler** | APScheduler 3.10 |
| **Notification** | Slack SDK 3.33 |
| **SSH** | Paramiko 3.5 |
| **HTTP Client** | httpx 0.27 |

---

## 10. API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/health` | 헬스 체크 |
| `POST` | `/api/incident` | LC → LogFixer webhook 수신 (202) |
| `GET` | `/api/incident/{log_hash}` | Incident 상세 조회 |
| `POST` | `/api/incident/{log_hash}/analyze` | 분석 수동 트리거 (dev/test) |
| `POST` | `/api/incident/{log_hash}/execute` | 실행 수동 트리거 (dev/test) |
| `POST` | `/api/incident/{log_hash}/resolve` | RESOLVED 처리 + LC 보고 |
| `POST` | `/api/slack/actions` | Slack Interactive Action 수신 |

---

## 11. 환경 설정

`.env.example` 을 복사하여 `.env` 로 사용합니다.

```bash
cp .env.example .env
```

| 변수 | 설명 | 예시 |
|---|---|---|
| `APP_ENV` | 실행 환경 | `development` / `production` |
| `APP_PORT` | 서버 포트 | `8000` |
| `DB_HOST` | MariaDB 호스트 | `localhost` |
| `DB_PORT` | MariaDB 포트 | `3306` |
| `DB_NAME` | DB 이름 | `logfixer` |
| `DB_USER` | DB 사용자 | `logfixer` |
| `DB_PASSWORD` | DB 비밀번호 | `logfixer1234` |
| `QDRANT_HOST` | Qdrant 호스트 | `localhost` |
| `QDRANT_PORT` | Qdrant 포트 | `6333` |
| `ES_HOST` | Elasticsearch URL | `http://localhost:9200` |
| `OPENAI_API_KEY` | OpenAI API 키 | `sk-...` |
| `SLACK_BOT_TOKEN` | Slack Bot 토큰 | `xoxb-...` |
| `SLACK_CHANNEL_ID` | 알림 채널 ID | `C...` |
| `LC_BASE_URL` | LogCollector 베이스 URL | `http://localhost:8080` |
| `LC_API_KEY` | LogCollector API 키 | |
| `SSH_DEFAULT_USER` | SSH 기본 사용자 | `ubuntu` |
| `SSH_DEFAULT_KEY_PATH` | SSH 개인키 경로 | `/home/ubuntu/.ssh/id_rsa` |

---

## 12. 실행 방법

### 인프라 (MariaDB + Qdrant + Elasticsearch)

```bash
cd docker
docker compose up -d
```

### 애플리케이션

```bash
# 의존성 설치
pip install -r requirements.txt

# 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 헬스 체크

```bash
curl http://localhost:8000/health
# {"status": "ok", "env": "development"}
```

---

## 13. 프로젝트 구조

```
LogFixer/
├── app/
│   ├── main.py                   # FastAPI 앱 진입점, lifespan 관리
│   ├── core/
│   │   ├── config.py             # 환경변수 설정 (pydantic-settings)
│   │   ├── enums.py              # IncidentState 열거형
│   │   └── exceptions.py         # 공통 예외 정의
│   ├── api/
│   │   ├── incident.py           # Incident CRUD + 분석/실행/해결 API
│   │   ├── slack_action.py       # Slack Interactive Action 수신
│   │   └── middleware.py         # 요청/응답 로깅 미들웨어
│   ├── analyzer/
│   │   ├── llm_analyzer.py       # RAG + LLM 분석 메인 로직
│   │   ├── validator.py          # 분석 결과 검증
│   │   └── prompts/              # root_cause / solution_rank 프롬프트
│   ├── agent/
│   │   ├── ssh_executor.py       # Paramiko SSH 명령 실행
│   │   ├── action_registry.py    # action_type → Action 클래스 매핑
│   │   ├── rollback.py           # 역순 롤백 실행
│   │   └── actions/
│   │       ├── restart.py        # RESTART 액션
│   │       ├── edit_config.py    # EDIT_CONFIG 액션
│   │       ├── clear_memory.py   # CLEAR_MEMORY 액션
│   │       └── del_disk.py       # DEL_DISK 액션
│   ├── rag/
│   │   ├── retriever.py          # RAG 통합 검색 (BM25 + kNN → RRF)
│   │   ├── embedder.py           # OpenAI 임베딩
│   │   └── kb_search.py          # ES BM25 검색
│   ├── vectordb/
│   │   ├── client.py             # Qdrant 클라이언트
│   │   └── store.py              # 컬렉션 초기화 및 벡터 저장
│   ├── notification/
│   │   └── slack.py              # Slack 승인 요청 / 해결 보고 발송
│   ├── reporter/
│   │   ├── kb_updater.py         # LC API 호출 (상태변경 + addendum)
│   │   └── generator.py          # addendum 텍스트 생성
│   ├── scheduler/
│   │   └── poller.py             # APScheduler 실행 감시 / 재발 감지
│   ├── status/
│   │   └── machine.py            # 상태머신 전이 로직 (upsert / transition)
│   ├── db/
│   │   ├── session.py            # AsyncSession 팩토리
│   │   └── models.py             # LfIncident SQLAlchemy 모델
│   └── schemas/                  # Pydantic 요청/응답 스키마
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml        # MariaDB + Qdrant + Elasticsearch
├── docs/
│   └── architecture.md           # 상세 아키텍처 문서
├── tests/
│   ├── unit/                     # 단위 테스트
│   └── integration/              # 통합 테스트
├── requirements.txt
└── .env.example
```
