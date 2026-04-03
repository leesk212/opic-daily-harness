# OPIC Daily Harness

4개의 AI Agent가 GitHub Issues를 통해 소통하며 매일 OPIC AL(Advanced Low) 등급 연습 문제를 자동 생성하고 KakaoTalk으로 전송하는 시스템입니다.

## Why "Harness"?

이 시스템을 **Harness**라고 부르는 이유는 소프트웨어 테스팅에서의 **Test Harness** 개념에서 차용했기 때문입니다.

Test Harness란 테스트 대상 모듈들을 **연결하고, 실행 순서를 제어하고, 결과를 수집**하는 프레임워크를 말합니다. 이 시스템도 동일한 역할을 합니다:

| Test Harness 개념 | 이 시스템에서의 대응 |
|---|---|
| **테스트 대상 모듈** | 4개의 AI Agent (Orchestrator, ContentManager, QuestionGenerator, Delivery) |
| **실행 제어** | GitHub Issues를 통한 순차적 파이프라인 트리거 |
| **모듈 간 통신** | Issue Comment가 메시지 큐 역할 (Agent 간 직접 호출 없음) |
| **결과 수집/추적** | 각 Agent의 실행 결과가 Issue Comment + SQLite + Langfuse에 기록 |
| **독립 실행** | 각 Agent는 독립 coroutine으로 실행, 다른 Agent 장애에 영향받지 않음 |

핵심은 **Agent들이 서로를 직접 호출하지 않는다**는 점입니다. Harness(GitHub Issues)가 중간에서 Agent 간 의존성을 관리하고, 각 Agent는 자기 차례가 왔는지만 폴링합니다. 이 구조 덕분에:

- **Agent를 독립적으로 교체/수정** 가능 (예: KakaoTalk → 다른 메신저 전환 시 Delivery Agent만 변경)
- **실행 이력이 자연스럽게 GitHub에 기록** (Issue = 파이프라인 실행 단위, Comment = Agent 실행 로그)
- **장애 격리** (하나의 Agent가 실패해도 다른 Agent는 계속 폴링)

## Architecture

```
+-------------------+          GitHub Issues (Harness Layer)                   +-------------------+
|                   |                                                          |                   |
|   Orchestrator    |  1. Issue 생성 ([Pipeline] OPIC Daily - 2026-04-03)      |   Dashboard       |
|   (스케줄 트리거)   | ------>  #42 [open, label: pipeline]                     |   (FastAPI)       |
|                   |          |                                               |                   |
+-------------------+          |                                               |  /api/harness-    |
                               v                                               |    status         |
+-------------------+    2. Comment: topic/type 선정                            |  /api/pipelines   |
|                   | ------>  "Topic: 해외 여행,                               |  /api/recipients  |
|  ContentManager   |           Type: 롤플레이 (Role Play)"                     |  /api/topics      |
|  (10초 polling)   |          |                                               |                   |
+-------------------+          v                                               +-------------------+
                         3. Comment: 문제 생성 결과                                     |
+-------------------+ ------>  "Question: Tell me about..."                    3초 polling으로
|                   |          |                                               실시간 Agent 상태
| QuestionGenerator |          v                                               모니터링
|  (15초 polling)   |    4. Comment: 전송 결과 + Issue close
+-------------------+
                      +-------------------+
                      |                   |
                      |    Delivery       | ------> KakaoTalk (kakaocli)
                      |   (10초 polling)  |         나와의 채팅 + 지정 수신자
                      +-------------------+
```

**핵심 원리:** 하나의 파이프라인 실행 = 하나의 GitHub Issue. 각 Agent의 실행 결과 = 해당 Issue의 Comment.

## Agent 역할

### Orchestrator
- 설정된 스케줄(기본 06:00, 12:00, 18:00, 00:00 KST)에 새 파이프라인 Issue를 생성합니다.
- `pipeline`, `agent:orchestrator`, `status:in-progress` 라벨을 부착합니다.
- 파이프라인 완료 시 최종 상태를 기록하고 Issue를 close합니다.

### ContentManager
- 10초 간격으로 새 파이프라인 Issue를 polling합니다.
- 선택된 OPIC 주제(웹 대시보드에서 설정 가능)와 8개 문제 유형(묘사, 과거 경험, 롤플레이, 콤보 세트 등) 중에서 선택합니다.
- 최근 7일간 출제된 주제/유형을 SQLite DB에서 조회하여 중복을 방지합니다.
- 선택 결과를 Issue Comment에 JSON으로 기록합니다.

### QuestionGenerator
- 15초 간격으로 ContentManager가 완료한 Issue를 polling합니다.
- ContentManager의 Comment에서 topic/question_type을 추출합니다.
- **Claude Code CLI** (`claude -p <prompt> --output-format text`)를 호출하여 AL 등급 문제를 생성합니다.
- 생성 결과(question, sample_answer, key_expressions, tip)를 SQLite에 저장하고 Issue Comment에 기록합니다.

### Delivery
- 10초 간격으로 QuestionGenerator가 완료한 Issue를 polling합니다.
- 메시지를 문제/답안 2개로 분할하여 구성합니다.
- **kakaocli** (UI 자동화)를 사용하여 설정된 수신자들에게 KakaoTalk 메시지를 전송합니다.
- 수신자별 전송 결과(성공/실패)를 Comment로 기록하고 Issue를 close합니다.

## 실행 구조

### Orchestrator = Scheduled Trigger (스케줄 트리거)

Orchestrator는 APScheduler를 통해 설정된 시각(06:00, 12:00, 18:00, 00:00 KST)에 GitHub Issue를 생성하는 트리거 역할입니다. 직접 다른 Agent를 호출하지 않고, Issue를 찍어내기만 합니다.

### 나머지 3개 Agent = Polling Worker (이벤트 드리븐)

ContentManager, QuestionGenerator, Delivery는 각각 독립적으로 GitHub Issues를 **폴링**하다가 자기 차례가 오면 처리합니다.

```
Orchestrator (스케줄에 따라 Issue 생성)
    ↓ GitHub Issue (label: pipeline, status:in-progress)
ContentManager (10초마다 폴링 → Issue 발견 → 댓글로 결과 기록)
    ↓ Issue 댓글
QuestionGenerator (15초마다 폴링 → CM 댓글 발견 → 댓글로 결과 기록)
    ↓ Issue 댓글
Delivery (10초마다 폴링 → QG 댓글 발견 → KakaoTalk 전송 → Issue 닫기)
```

| 에이전트 | 실행 패턴 | 간격 | 동작 |
|---------|----------|------|------|
| **Orchestrator** | 스케줄 (APScheduler) | 06/12/18/00시 | GitHub Issue를 생성하여 파이프라인 트리거 |
| **ContentManager** | 폴링 (이벤트 드리븐) | 10초 | `status:in-progress` Issue를 감시, 자기 댓글이 없으면 주제/유형 선택 |
| **QuestionGenerator** | 폴링 (이벤트 드리븐) | 15초 | ContentManager 댓글이 달린 Issue를 감시, 문제 생성 |
| **Delivery** | 폴링 (이벤트 드리븐) | 10초 | QuestionGenerator 댓글이 달린 Issue를 감시, KakaoTalk 전송 후 Issue 닫기 |

**핵심:** Agent 간 직접 호출은 없고, **GitHub Issues 댓글이 메시지 큐 역할**을 합니다. 각 Agent는 `asyncio`로 독립 실행되며, Issue Comment의 `Agent: \`{name}\`` 패턴으로 이전 Agent의 완료 여부를 판별합니다.

## Dashboard

FastAPI 기반 웹 대시보드로 시스템 상태를 모니터링합니다. Harness와 동일 프로세스에서 별도 스레드로 실행됩니다.

| 기능 | 설명 |
|------|------|
| **실시간 Agent 상태** | 3초 polling으로 4개 Agent의 현재 상태(running/polling/done/error) 표시. Pulse 애니메이션으로 활성 여부 시각화 |
| **Pipeline History** | GitHub Issues에서 가져온 파이프라인 목록. 클릭하면 Agent별 실행 단계(Comment)를 시간순으로 확인 가능 |
| **Question Browser** | 생성된 OPIC 문제를 주제/유형/날짜별로 조회 |
| **통계** | 총 문제 수, 전송 성공/실패 수, 주제/유형별 분포 차트 |
| **Agent Logs** | 로컬 SQLite DB에 기록된 Agent 활동 로그 및 Delivery 이력 |
| **Settings** | KakaoTalk 수신자 관리 (추가/삭제/수정), OPIC 주제 선택 |

Dashboard 접속: `http://localhost:8080` (Admin 모드: `http://localhost:8080/?admin`)

## Setup

### 1. 사전 요구사항

- Python 3.9+
- [GitHub CLI (`gh`)](https://cli.github.com/) 설치 및 인증 (`gh auth login`)
- [Claude Code CLI (`claude`)](https://docs.anthropic.com/en/docs/claude-code) 설치
- [kakaocli](https://github.com/silver-flight-group/kakaocli) 설치 (`~/bin/kakaocli`)
- macOS KakaoTalk 앱 설치 및 로그인
- Accessibility 권한 (시스템 설정 → 개인정보 보호 → 손쉬운 사용 → 터미널 앱 허용)

### 2. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집합니다:

```env
SCHEDULE_HOURS=6,12,18,0
DASHBOARD_PORT=8080
KAKAOCLI_PATH=~/bin/kakaocli
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 실행

```bash
# Harness + Dashboard 동시 실행
python run.py

# 즉시 1회 트리거 후 스케줄 모드
python run.py --run-now

# Dashboard만 실행
python run.py --dashboard
```

실행하면 4개 Agent Worker가 `asyncio`로 동시 시작되며, Dashboard는 별도 스레드에서 구동됩니다. `Ctrl+C`로 graceful shutdown됩니다.

## Tech Stack

| 구성 요소 | 기술 |
|-----------|------|
| Agent 실행 | Python asyncio (4개 독립 coroutine) |
| Agent 간 통신 | GitHub Issues + Comments (`gh` CLI) |
| 문제 생성 | Claude Code CLI (`claude -p`) |
| 데이터 저장 | SQLite (aiosqlite) |
| KakaoTalk 전송 | kakaocli (macOS UI 자동화) |
| 트레이싱 | Langfuse |
| Dashboard | FastAPI + Jinja2 + Vanilla JS |
| Dashboard 서버 | Uvicorn |
| 스케줄링 | APScheduler |
| 설정 관리 | python-dotenv + JSON 파일 |

## Project Structure

```
opic-daily-harness/
├── run.py                  # 진입점 (Harness + Dashboard + Scheduler 동시 실행)
├── harness_runner.py       # 4개 Agent Worker를 asyncio로 상시 실행
├── harness.py              # GitHub Issues 통신 레이어 (GitHubHarness 클래스)
├── tracing.py              # Langfuse 트레이싱 유틸
├── config.py               # 환경 변수, OPIC 주제/유형 목록, 수신자 관리
├── db.py                   # SQLite 스키마 및 CRUD (questions, delivery_log, agent_log)
├── agents/
│   ├── content_manager.py  # 주제/유형 선택 Agent (중복 방지 로직)
│   ├── question_generator.py # Claude Code CLI로 문제 생성 Agent
│   └── delivery.py         # KakaoTalk 전송 Agent (kakaocli)
├── dashboard/
│   ├── app.py              # FastAPI 앱 (REST API 엔드포인트)
│   └── templates/
│       └── index.html      # SPA 대시보드 (3초 polling 실시간 UI)
├── data/                   # SQLite DB, JSON 설정, 로그 (자동 생성)
│   ├── opic.db
│   ├── kakao_recipients.json
│   └── selected_topics.json
├── requirements.txt
├── .env.example
└── README.md
```
