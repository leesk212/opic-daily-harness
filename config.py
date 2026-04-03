import os
from dotenv import load_dotenv

load_dotenv()

# KakaoTalk delivery via kakaocli (UI automation)
KAKAOCLI_PATH = os.getenv("KAKAOCLI_PATH", os.path.expanduser("~/bin/kakaocli"))
KAKAO_RECIPIENTS_PATH = os.path.join(os.path.dirname(__file__), "data", "kakao_recipients.json")
SELECTED_TOPICS_PATH = os.path.join(os.path.dirname(__file__), "data", "selected_topics.json")

_DEFAULT_RECIPIENTS = [
    {"name": "me", "self": True},
    {"name": "16추호성", "self": False},
]

def load_kakao_recipients():
    import json
    try:
        with open(KAKAO_RECIPIENTS_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        save_kakao_recipients(_DEFAULT_RECIPIENTS)
        return _DEFAULT_RECIPIENTS

def save_kakao_recipients(recipients):
    import json
    os.makedirs(os.path.dirname(KAKAO_RECIPIENTS_PATH), exist_ok=True)
    with open(KAKAO_RECIPIENTS_PATH, "w") as f:
        json.dump(recipients, f, ensure_ascii=False, indent=2)


# 기본 선택 주제 12개
_DEFAULT_SELECTED_TOPICS = [
    "자기소개", "거주지/집", "여가/취미", "음악 감상", "영화 보기", "공원 가기",
    "해변/바다", "국내 여행", "해외 여행", "쇼핑", "요리/음식", "건강/운동",
]

def load_selected_topics():
    import json
    try:
        with open(SELECTED_TOPICS_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        save_selected_topics(_DEFAULT_SELECTED_TOPICS)
        return _DEFAULT_SELECTED_TOPICS

def save_selected_topics(topics):
    import json
    os.makedirs(os.path.dirname(SELECTED_TOPICS_PATH), exist_ok=True)
    with open(SELECTED_TOPICS_PATH, "w") as f:
        json.dump(topics, f, ensure_ascii=False, indent=2)

# Claude Code CLI is used for question generation (no API key needed)

# Schedule: comma-separated hours in KST (e.g. "6,12,18,0")
SCHEDULE_HOURS = [int(h.strip()) for h in os.getenv("SCHEDULE_HOURS", "6,12,18,0").split(",")]
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# OPIC Settings
OPIC_TARGET_LEVEL = "AL"  # Advanced Low

OPIC_TOPICS = [
    "자기소개",
    "거주지/집",
    "여가/취미",
    "음악 감상",
    "영화 보기",
    "공원 가기",
    "해변/바다",
    "국내 여행",
    "해외 여행",
    "쇼핑",
    "요리/음식",
    "건강/운동",
    "기술/인터넷",
    "직장/업무",
    "학교/교육",
    "날씨/계절",
    "교통수단",
    "뉴스/이슈",
    "재활용/환경",
    "호텔 예약",
    "식당 예약",
    "은행 업무",
]

OPIC_QUESTION_TYPES = [
    "자기소개 (Self-Introduction)",
    "묘사 (Description)",
    "습관/루틴 (Habit/Routine)",
    "과거 경험 (Past Experience)",
    "비교 (Comparison)",
    "돌발 질문 (Unexpected Question)",
    "롤플레이 (Role Play)",
    "콤보 세트 (Combo Set - 3연속 질문)",
]

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "opic.db")
LOG_DIR = os.path.join(os.path.dirname(__file__), "data", "logs")
