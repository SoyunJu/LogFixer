# LogFixer 아키텍처 문서

## 개요

LogFixer는 LogCollector(LC)와 연동하여 장애 발생 시 자동으로 원인을 분석하고,
담당자의 Slack 승인 후 AI agent가 직접 해결을 실행하는 자동화 시스템이다.

---

## 1. LC ↔ LogFixer 연동

### 연동 흐름 요약

```
LC                           LogFixer
│                               │
│── POST /api/incident ────────>│  incident 실시간 전달 (webhook push)
│                               │
│                               │  분석 → Slack 승인 요청
│                               │
│<── PATCH /incidents/{logHash}/status  상태 변경 (RESOLVED)
│<── GET  /kb/articles/by-hash/{logHash}  kbArticleId 조회
│<── POST /kb/{kbArticleId}/addendums     addendum 저장
│                               │
│  (polling: 30초/5분 간격)     │
│<── 내부 상태 확인              │  해결 확인, 재발 감지
```

### 방향별 방식

| 방향 | 방식 | 설명 |
|---|---|---|
| LC → LogFixer | webhook push | LC에서 incident 생성 시 `POST /api/incident`로 실시간 전달 |
| LogFixer → LC | REST API 호출 | 해결 완료 후 상태 변경 및 addendum 저장 |
| LogFixer 내부 | polling (APScheduler) | 해결 확인(30초) 및 재발 감지(5분) |

### polling 기준

- **해결 확인** (30초 간격, `EXECUTING` 상태): SSH 실행 완료 여부 확인
- **재발 감지** (5분 간격, `RESOLVED` 상태): `repeat_count` 증가 또는 `last_occurred_at` 갱신 감지

---

## 2. LogFixer → LC 호출 API

해결 완료 후 아래 순서로 LC API를 순차 호출한다.

| 순서 | 용도 | 메서드 | 경로 |
|---|---|---|---|
| 1 | Incident 상태 변경 | `PATCH` | `/api/incidents/{logHash}/status` |
| 2 | kbArticleId 조회 | `GET` | `/api/kb/articles/by-hash/{logHash}` |
| 3 | addendum 저장 | `POST` | `/api/kb/{kbArticleId}/addendums` |

### 상세 설명

#### 1. Incident 상태 변경
```
PATCH /api/incidents/{logHash}/status
Body: { "status": "RESOLVED" }
```
담당자가 Slack 보고서의 `[상태변경 승인]` 버튼을 누르면 호출됨.
LogFixer가 직접 변경하지 않고 반드시 담당자 승인 후에만 실행.

#### 2. kbArticleId 조회
```
GET /api/kb/articles/by-hash/{logHash}
```
상태 변경 직후 LC가 KbArticle을 생성하는 데 시간이 필요할 수 있으므로
**최대 N회 retry** (delay 포함) 후 kbArticleId를 확보한다.

#### 3. addendum 저장
```
POST /api/kb/{kbArticleId}/addendums
Body: {
  "content": "장애 분석 결과 및 해결 과정 요약",
  "resolvedAt": "2025-01-01T00:00:00Z",
  "actionsTaken": ["서비스 재시작", "heap 설정 변경"]
}
```
해결 방법, 실행 이력, 분석 결과를 KbArticle에 추가한다.
이 데이터는 이후 유사 장애 발생 시 RAG 검색에 활용된다.

---

## 3. Qdrant 컬렉션 구조

LogFixer는 RAG(Retrieval-Augmented Generation)를 위해 Qdrant 벡터 DB를 사용한다.

### 컬렉션 목록

| 컬렉션 | 저장 데이터 | 주요 용도 |
|---|---|---|
| `kb_articles` | KbArticle + addednum 임베딩 | 유사 문서 검색 |
| `error_patterns` | 과거 에러 패턴 | 유사 에러 검색 |
| `solutions` | 검증된 해결법 | 해결법 검증 및 재활용 |

### 컬렉션별 상세

#### `kb_articles`
LC ES에 저장된 KbArticle 및 LogFixer가 추가한 addednum을 임베딩하여 저장.
ES BM25 검색과 함께 **하이브리드 검색(BM25 + kNN → RRF 재랭킹)**에 활용된다.

```
payload 예시:
{
  "kbArticleId": "abc123",
  "logHash": "sha256...",
  "title": "OOMKilled - Java heap space",
  "content": "...",
  "addednum": "서비스 재시작 및 heap 4G 증가로 해결",
  "resolvedCount": 3
}
```

#### `error_patterns`
과거에 발생한 에러의 패턴(stacktrace 요약, 에러 메시지)을 임베딩하여 저장.
신규 incident 유입 시 유사 에러를 빠르게 탐색하는 데 사용한다.

```
payload 예시:
{
  "patternId": "uuid",
  "errorType": "OutOfMemoryError",
  "stacktraceSummary": "...",
  "firstOccurredAt": "2025-01-01T00:00:00Z",
  "occurrenceCount": 12
}
```

#### `solutions`
실제로 적용되어 검증된 해결법을 저장. LLM이 해결법을 제안할 때
유사 사례의 검증된 해결법을 우선 참조하도록 한다.

```
payload 예시:
{
  "solutionId": "uuid",
  "errorPatternId": "uuid",
  "actions": [
    {"type": "RESTART", "target": "service-name"},
    {"type": "EDIT_CONFIG", "file": "/etc/app.conf", "key": "heap", "value": "4g"}
  ],
  "successCount": 5,
  "lastUsedAt": "2025-01-01T00:00:00Z"
}
```

### 검색 전략 (RAG)

```
신규 incident 수신
       │
       ▼
  [ES BM25 검색]          키워드 기반 KbArticle 검색
       +
  [Qdrant kNN 검색]       벡터 유사도 기반 검색
       │                  (kb_articles + error_patterns)
       ▼
  [RRF 재랭킹]            Reciprocal Rank Fusion으로 결과 통합
       │
       ▼
  [LLM 컨텍스트 주입]     상위 k개 문서를 프롬프트에 포함
       │
       ▼
  원인 분석 + 해결법 순위 선정
```

---

## 4. 상태머신 (IncidentState)

```
RECEIVED
   │
   ▼
ANALYZING
   │
   ▼
PENDING_APPROVAL  ──(담당자 Reject)──> RECEIVED (재분석)
   │
   ▼ (담당자 Approve)
EXECUTING
   │
   ├──(성공)──> RESOLVED
   │
   └──(실패)──> ROLLING_BACK
                    │
                    ├──(복구 성공, retry < 3)──> RECEIVED (재시도)
                    │
                    └──(retry 초과 or 복구 실패)──> ESCALATED
```

상태는 MariaDB `lf_incident` 테이블에 저장되며,
`RESOLVED` 상태 전환은 반드시 담당자가 Slack 버튼으로 승인해야 한다.

---

## 5. Slack 알림 흐름

### 1단계: 분석 완료 알림 (승인 요청)
```
[LogFixer] 장애 분석 완료
────────────────────────────
Host: prod-web-01
Error: OutOfMemoryError (Java heap space)
원인: 메모리 누수 - heap 용량 부족 (신뢰도 87%)
해결법:
  1. 서비스 재시작
  2. /etc/app.conf heap 설정 4G로 변경
근거: KbArticle #42, #17
────────────────────────────
[✅ 승인]  [❌ 거절]
```

### 2단계: 실행 완료 보고서 (상태 변경 승인)
```
[LogFixer] 장애 해결 보고서
────────────────────────────
Host: prod-web-01
발생: 2025-01-01 09:00
해결: 2025-01-01 09:15 (15분 소요)
실행 내역:
  - 서비스 재시작 (✅ 성공)
  - heap 설정 변경: 2G → 4G (✅ 성공)
────────────────────────────
[✅ RESOLVED로 상태 변경]
```
