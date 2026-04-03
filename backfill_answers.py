"""Backfill script: 기존 질문들의 sample_answer를 Claude CLI로 재생성

Usage:
    python backfill_answers.py
"""

import asyncio
import json
import subprocess
import sqlite3
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "opic.db")
ARCHIVE_PATH = os.path.join(os.path.dirname(__file__), "data", "questions_archive.json")

ANSWER_PROMPT = """당신은 OPIC AL(Advanced Low) 등급 전문 답변 코치입니다.

주제: {topic}
문제 유형: {question_type}

아래 OPIC 질문에 대한 AL 등급 수준의 모범 답변을 작성하세요.

질문:
{question}

규칙:
1. 답변은 영어로 작성합니다 (실제 OPIC 시험과 동일).
2. AL 등급에 맞는 자연스럽고 유창한 답변을 작���합니다.
3. 200단어 이상으로 구체적이고 개인적인 경험을 포함합니다.
4. 다양한 어휘와 문법 구조를 활용합니다.
5. 콤보 세트 질문이면 각 질문에 모두 답합니다.

반드시 아래 JSON ���식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력:
{{"sample_answer": "AL등급 수준의 모범 답변 (영어, 200단어 이상)"}}"""


def get_questions_without_answers():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, topic, question_type, question_text, sample_answer FROM questions ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return [r for r in rows if not r["sample_answer"] or r["sample_answer"].strip() == ""]


def generate_answer(question_row):
    prompt = ANSWER_PROMPT.format(
        topic=question_row["topic"],
        question_type=question_row["question_type"],
        question=question_row["question_text"],
    )
    proc = subprocess.Popen(
        ["claude", "-p", prompt, "--output-format", "text"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        return None

    if proc.returncode != 0:
        return None

    text = stdout.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        data = json.loads(text.strip())
        return data.get("sample_answer", "")
    except json.JSONDecodeError:
        return text.strip()


def update_db(question_id, sample_answer):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE questions SET sample_answer = ? WHERE id = ?",
        (sample_answer, question_id),
    )
    conn.commit()
    conn.close()


def update_archive(question_id, sample_answer):
    if not os.path.exists(ARCHIVE_PATH):
        return
    with open(ARCHIVE_PATH, "r", encoding="utf-8") as f:
        archive = json.load(f)
    for entry in archive:
        if entry.get("id") == question_id:
            entry["sample_answer"] = sample_answer
            break
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


def main():
    questions = get_questions_without_answers()
    total = len(questions)
    print(f"{'='*60}")
    print(f"  OPIC Backfill Pipeline - {total} questions to process")
    print(f"  Target: AL (Advanced Low) sample answers")
    print(f"{'='*60}\n")

    if total == 0:
        print("  All questions already have sample answers. Done!")
        return

    success = 0
    failed = 0

    for i, q in enumerate(questions, 1):
        qid = q["id"]
        topic = q["topic"]
        qtype = q["question_type"]
        now = datetime.now(KST).strftime("%H:%M:%S")

        print(f"  [{i}/{total}] #{qid} {topic} / {qtype}")
        print(f"    Started at {now} ... ", end="", flush=True)

        answer = generate_answer(q)

        if answer:
            update_db(qid, answer)
            update_archive(qid, answer)
            success += 1
            print(f"OK ({len(answer)} chars)")
        else:
            failed += 1
            print("FAILED")

    print(f"\n{'='*60}")
    print(f"  Backfill complete: {success} success, {failed} failed (out of {total})")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
