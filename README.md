# OPIC Daily Harness

4개의 AI Agent가 GitHub Issues를 통해 소통하며 매일 OPIC AL(Advanced Low) 등급 연습 문제를 자동 생성하고 Slack으로 전송하는 시스템입니다.

## Architecture

```
+-------------------+          GitHub Issues (Communication Layer)          +-------------------+
|                   |                                                       |                   |
|   Orchestrator    |  1. Issue 생성 ([Pipeline] OPIC Daily - 2026-04-03)   |   Dashboard       |
|   (주기적 트리거)   | ------>  #42 [open, label: pipeline]                  |   (FastAPI)       |
|                   |          |                                            |                   |
+-------------------+          |                                            |  /api/harness-    |
                               v                                            |    status         |
+-------------------+    2. Comment: topic/type 선정                         |  /api/pipelines   |
|                   | ------>  "Topic: 해외 여행,                            |  /api/questions   |
|  ContentManager   |           Type: 롤플레이 (Role Play)"                  |  /api/stats       |
|  (10초 polling)   |          |                                            |                   |
+-------------------+          v                                            +-------------------+
                         3. Comment: 문제 생성 결과                                  |
+-------------------+ ------>  "Question: Tell me about..."                  3초 polling으로
|                   |          |                                             실시간 Agent 상태
| QuestionGenerator |          v                                             모니터링
|  (15초 polling)   |    4. Comment: 전송 결과 + Issue close
+-------------------+
                      +-------------------+
                      |                   |
                      |    Delivery       | ------> Slack Channel
                      |   (10초 polling)  |         (Block Kit 메시지)
                      +-------------------+
```

**핵심 원리:** 하나의 파이프라인 실행 = 하나의 GitHub Issue. 각 Agent의 실행 결과 = 해당 Issue의 Comment.

## Agent 역할

### Orchestrator
- 설정된 간격(기본 300초)마다 새 파이프라인 Issue를 생성합니다.
- `pipeline`, `agent:orchestrator`, `status:in-progress` 라벨을 부착합니다.
- 파이프라인 완료 시 최종 상태를 기록하고 Issue를 close합니다.

### ContentManager
- 10초 간격으로 새 파이프라인 Issue를 polling합니다.
- 22개 OPIC 주제(자기소개, 거주지, 여가/취미, 해외 여행 등)와 8개 문제 유형(묘사, 과거 경험, 롤플레이, 콤보 세트 등) 중에서 선택합니다.
- 최근 7일간 출제된 주제/유형을 SQLite DB에서 조회하여 중복을 방지합니다.
- 선택 결과를 Issue Comment에 JSON으로 기록합니다.

### QuestionGenerator
- 15초 간격으로 ContentManager가 완료한 Issue를 polling합니다.
- ContentManager의 Comment에서 topic/question_type을 추출합니다.
- **Claude Code CLI** (`claude -p <prompt> --output-format text`)를 호출하여 AL 등급 문제를 생성합니다.
- 생성 결과(question, sample_answer, key_expressions, tip)를 SQLite에 저장하고 Issue Comment에 기록합니다.

### Delivery
- 10초 간격으로 QuestionGenerator가 완료한 Issue를 polling합니다.
- Slack Block Kit 형식으로 메시지를 구성합니다 (Question, Key Expressions, Tip, Sample Answer).
- `slack-sdk`를 사용하여 지정된 Slack 채널에 전송합니다.
- 전송 성공/실패를 Comment로 기록하고 Issue를 close합니다.

## 실행 구조

### Orchestrator = Cron Job (배치 트리거)

Orchestrator는 설정된 간격(기본 300초)마다 GitHub Issue를 생성하는 **배치성 cron job** 역할입니다. 직접 다른 Agent를 호출하지 않고, Issue를 찍어내기만 합니다.

### 나머지 3개 Agent = Polling Worker (이벤트 드리븐)

ContentManager, QuestionGenerator, Delivery는 각각 독립적으로 GitHub Issues를 **폴링**하다가 자기 차례가 오면 처리합니다.

```
Orchestrator (300초마다 Issue 생성)
    ↓ GitHub Issue (label: pipeline, status:in-progress)
ContentManager (10초마다 폴링 → Issue 발견 → 댓글로 결과 기록)
    ↓ Issue 댓글
QuestionGenerator (15초마다 폴링 → CM 댓글 발견 → 댓글로 결과 기록)
    ↓ Issue 댓글
Delivery (10초마다 폴링 → QG 댓글 발견 → Slack 전송 → Issue 닫기)
```

| 에이전트 | 실행 패턴 | 간격 | 동작 |
|---------|----------|------|------|
| **Orchestrator** | 배치 (타이머) | 300초 | 주기적으로 GitHub Issue를 생성하여 파이프라인 트리거 |
| **ContentManager** | 폴링 (이벤트 드리븐) | 10초 | `status:in-progress` Issue를 감시, 자기 댓글이 없으면 주제/유형 선택 |
| **QuestionGenerator** | 폴링 (이벤트 드리븐) | 15초 | ContentManager 댓글이 달린 Issue를 감시, 문제 생성 |
| **Delivery** | 폴링 (이벤트 드리븐) | 10초 | QuestionGenerator 댓글이 달린 Issue를 감시, Slack 전송 후 Issue 닫기 |

**핵심:** Agent 간 직접 호출은 없고, **GitHub Issues 댓글이 메시지 큐 역할**을 합니다. 각 Agent는 `asyncio`로 독립 실행되며, Issue Comment의 `Agent: \`{name}\`` 패턴으로 이전 Agent의 완료 여부를 판별합니다.

## Dashboard

FastAPI 기반 웹 대시보드로 시스템 상태를 모니터링합니다. Harness와 동일 프로세스에서 별도 스레드로 실행됩니다.

| 기능 | 설명 |
|------|------|
| **실시간 Agent 상태** | 3초 polling으로 4개 Agent의 현재 상태(running/polling/done/error/sleeping) 표시. Pulse 애니메이션으로 활성 여부 시각화 |
| **Pipeline History** | GitHub Issues에서 가져온 파이프라인 목록. 클릭하면 Agent별 실행 단계(Comment)를 시간순으로 확인 가능 |
| **Question Browser** | 생성된 OPIC 문제를 주제/유형/날짜별로 조회 |
| **통계** | 총 문제 수, 전송 성공/실패 수, 주제/유형별 분포 차트 |
| **Agent Logs** | 로컬 SQLite DB에 기록된 Agent 활동 로그 및 Delivery 이력 |

Dashboard 접속: `http://localhost:8080`

## Setup

### 1. 사전 요구사항

- Python 3.9+
- [GitHub CLI (`gh`)](https://cli.github.com/) 설치 및 인증 (`gh auth login`)
- [Claude Code CLI (`claude`)](https://docs.anthropic.com/en/docs/claude-code) 설치
- Slack Bot Token (문제 전송용)

### 2. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집합니다:

```env
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_CHANNEL_ID=C0123456789

DAILY_SEND_HOUR=8
DAILY_SEND_MINUTE=0

DASHBOARD_PORT=8080
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. 실행

```bash
# Harness + Dashboard 동시 실행 (기본 5분 간격)
python run.py

# 파이프라인 간격 지정 (60초)
python run.py --interval 60

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
| Slack 전송 | slack-sdk (Block Kit) |
| Dashboard | FastAPI + Jinja2 + Vanilla JS |
| Dashboard 서버 | Uvicorn |
| 설정 관리 | python-dotenv |

## Project Structure

```
opic-daily-harness/
├── run.py                  # 진입점 (Harness + Dashboard 동시 실행)
├── harness_runner.py       # 4개 Agent Worker를 asyncio로 상시 실행
├── harness.py              # GitHub Issues 통신 레이어 (GitHubHarness 클래스)
├── config.py               # 환경 변수, OPIC 주제/유형 목록, 설정값
├── db.py                   # SQLite 스키마 및 CRUD (questions, delivery_log, agent_log)
├── agents/
│   ├── orchestrator.py     # 파이프라인 조율 Agent
│   ├── content_manager.py  # 주제/유형 선택 Agent (중복 방지 로직)
│   ├── question_generator.py # Claude Code CLI로 문제 생성 Agent
│   └── delivery.py         # Slack 전송 Agent
├── dashboard/
│   ├── app.py              # FastAPI 앱 (REST API 엔드포인트)
│   └── templates/
│       └── index.html      # SPA 대시보드 (3초 polling 실시간 UI)
├── data/                   # SQLite DB 및 로그 (자동 생성)
├── requirements.txt
├── .env.example
└── README.md
```
