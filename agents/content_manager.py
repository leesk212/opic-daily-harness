"""Content Manager Agent - 주제/유형 선택 및 중복 방지"""

import random
from db import get_recent_topics, log_agent
from config import OPIC_TOPICS, OPIC_QUESTION_TYPES, load_selected_topics


class ContentManagerAgent:
    name = "ContentManager"

    async def pick_topic_and_type(self) -> dict:
        await log_agent(self.name, "pick_topic_and_type", "started")

        try:
            recent = await get_recent_topics(days=7)
            recent_topics = [r["topic"] for r in recent]
            recent_types = [r["question_type"] for r in recent]

            # 사용자가 선택한 12개 주제만 사용
            selected = load_selected_topics()

            # 최근 7일간 안 나온 주제 우선
            available_topics = [t for t in selected if t not in recent_topics]
            if not available_topics:
                available_topics = selected

            # 최근 7일간 덜 나온 유형 우선
            type_counts = {}
            for qt in OPIC_QUESTION_TYPES:
                type_counts[qt] = recent_types.count(qt)
            min_count = min(type_counts.values()) if type_counts else 0
            available_types = [t for t, c in type_counts.items() if c == min_count]

            topic = random.choice(available_topics)
            question_type = random.choice(available_types)

            result = {"topic": topic, "question_type": question_type}
            await log_agent(self.name, "pick_topic_and_type", "success", str(result))
            return result

        except Exception as e:
            await log_agent(self.name, "pick_topic_and_type", "failed", str(e))
            return {
                "topic": random.choice(load_selected_topics()),
                "question_type": random.choice(OPIC_QUESTION_TYPES),
            }
