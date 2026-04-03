import os
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "")
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
