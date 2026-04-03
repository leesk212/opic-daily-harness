import aiosqlite
import json
import os
from datetime import datetime, timezone, timedelta
from config import DB_PATH

ARCHIVE_PATH = os.path.join(os.path.dirname(__file__), "data", "questions_archive.json")

KST = timezone(timedelta(hours=9))


def _kst_now() -> str:
    """현재 KST 시각을 ISO 형식 문자열로 반환"""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                question_type TEXT NOT NULL,
                question_text TEXT NOT NULL,
                sample_answer TEXT,
                key_expressions TEXT,
                created_at TIMESTAMP DEFAULT (datetime('now', '+9 hours'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER,
                channel TEXT,
                status TEXT NOT NULL,
                error_message TEXT,
                delivered_at TIMESTAMP DEFAULT (datetime('now', '+9 hours')),
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                created_at TIMESTAMP DEFAULT (datetime('now', '+9 hours'))
            )
        """)
        await db.commit()


async def log_agent(agent_name: str, action: str, status: str, detail: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO agent_log (agent_name, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (agent_name, action, status, detail, _kst_now()),
        )
        await db.commit()


async def save_question(topic, question_type, question_text, sample_answer="", key_expressions="", tip="", issue_number=None):
    created_at = _kst_now()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO questions (topic, question_type, question_text, sample_answer, key_expressions, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (topic, question_type, question_text, sample_answer, key_expressions, created_at),
        )
        await db.commit()
        question_id = cursor.lastrowid

    # Git-tracked archive에 누적 저장
    _append_to_archive({
        "id": question_id,
        "issue_number": issue_number,
        "topic": topic,
        "question_type": question_type,
        "question": question_text,
        "key_expressions": key_expressions,
        "tip": tip,
        "sample_answer": sample_answer,
        "created_at": created_at,
    })
    return question_id


def _append_to_archive(entry: dict):
    """질문을 git-tracked JSON 파일에 누적 저장"""
    archive = []
    if os.path.exists(ARCHIVE_PATH):
        try:
            with open(ARCHIVE_PATH, "r", encoding="utf-8") as f:
                archive = json.load(f)
        except (json.JSONDecodeError, IOError):
            archive = []
    archive.append(entry)
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


async def save_delivery(question_id, channel, status, error_message=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO delivery_log (question_id, channel, status, error_message, delivered_at) VALUES (?, ?, ?, ?, ?)",
            (question_id, channel, status, error_message, _kst_now()),
        )
        await db.commit()


async def get_recent_topics(days=7):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT topic, question_type FROM questions WHERE created_at >= datetime('now', '+9 hours', ?)",
            (f"-{days} days",),
        )
        return await cursor.fetchall()


async def get_all_questions(limit=50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM questions ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return await cursor.fetchall()


async def get_delivery_logs(limit=50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM delivery_log ORDER BY delivered_at DESC LIMIT ?", (limit,)
        )
        return await cursor.fetchall()


async def get_agent_logs(limit=100):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM agent_log ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return await cursor.fetchall()


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        total_q = await db.execute_fetchall("SELECT COUNT(*) FROM questions")
        total_d = await db.execute_fetchall(
            "SELECT COUNT(*) FROM delivery_log WHERE status='success'"
        )
        total_f = await db.execute_fetchall(
            "SELECT COUNT(*) FROM delivery_log WHERE status='failed'"
        )
        topic_dist = await db.execute_fetchall(
            "SELECT topic, COUNT(*) as cnt FROM questions GROUP BY topic ORDER BY cnt DESC LIMIT 10"
        )
        type_dist = await db.execute_fetchall(
            "SELECT question_type, COUNT(*) as cnt FROM questions GROUP BY question_type ORDER BY cnt DESC"
        )
        return {
            "total_questions": total_q[0][0],
            "successful_deliveries": total_d[0][0],
            "failed_deliveries": total_f[0][0],
            "topic_distribution": [(r[0], r[1]) for r in topic_dist],
            "type_distribution": [(r[0], r[1]) for r in type_dist],
        }
