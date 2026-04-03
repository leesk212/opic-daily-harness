"""Orchestrator Agent - GitHub Issues harness를 통해 파이프라인 조율"""

import traceback
from db import log_agent, init_db
from harness import GitHubHarness, ensure_labels
from agents.content_manager import ContentManagerAgent
from agents.question_generator import QuestionGeneratorAgent
from agents.delivery import DeliveryAgent


class OrchestratorAgent:
    name = "Orchestrator"

    def __init__(self):
        self.harness = GitHubHarness()
        self.content_manager = ContentManagerAgent()
        self.question_generator = QuestionGeneratorAgent()
        self.delivery = DeliveryAgent()

    async def run_pipeline(self) -> dict:
        """일일 OPIC 문제 생성 및 전송 파이프라인 실행"""
        await init_db()
        await log_agent(self.name, "run_pipeline", "started")

        # GitHub Labels 초기화
        ensure_labels()

        # Pipeline Issue 생성
        issue_number = self.harness.create_pipeline_issue()
        self.harness.post_agent_status(
            issue_number, self.name, "pipeline_start", "started",
            {"message": "Daily OPIC pipeline initiated"},
        )

        result = {"status": "unknown", "issue_number": issue_number, "steps": {}}

        try:
            # Step 1: Content Manager → 주제/유형 선택
            self.harness.post_agent_status(
                issue_number, self.content_manager.name, "pick_topic_and_type", "started",
            )
            selection = await self.content_manager.pick_topic_and_type()
            self.harness.post_agent_status(
                issue_number, self.content_manager.name, "pick_topic_and_type", "success",
                selection,
            )
            result["steps"]["content_selection"] = selection

            # Step 2: Question Generator → 문제 생성
            self.harness.post_agent_status(
                issue_number, self.question_generator.name, "generate", "started",
                {"topic": selection["topic"], "type": selection["question_type"]},
            )
            question_data = await self.question_generator.generate(
                topic=selection["topic"],
                question_type=selection["question_type"],
            )
            # 댓글에는 핵심 정보만 (sample_answer는 길어서 요약)
            harness_data = {
                "question_id": question_data.get("id"),
                "question": question_data.get("question", ""),
                "key_expressions": question_data.get("key_expressions", ""),
                "tip": question_data.get("tip", ""),
            }
            self.harness.post_agent_status(
                issue_number, self.question_generator.name, "generate", "success",
                harness_data,
            )
            result["steps"]["question"] = question_data

            # Step 3: Delivery → KakaoTalk 전송
            self.harness.post_agent_status(
                issue_number, self.delivery.name, "send", "started",
            )
            delivered = await self.delivery.send(question_data)
            self.harness.post_agent_status(
                issue_number, self.delivery.name, "send",
                "success" if delivered else "failed",
                {"delivered": delivered},
            )
            result["steps"]["delivery"] = {"success": delivered}

            # Pipeline 완료
            final_status = "success" if delivered else "failed"
            result["status"] = final_status
            self.harness.post_agent_status(
                issue_number, self.name, "pipeline_complete", final_status,
                {"summary": f"Topic: {selection['topic']}, Type: {selection['question_type']}, Delivered: {delivered}"},
            )
            self.harness.close_pipeline_issue(issue_number, final_status)
            await log_agent(self.name, "run_pipeline", final_status)

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()

            self.harness.post_agent_status(
                issue_number, self.name, "pipeline_error", "failed",
                {"error": str(e)},
            )
            self.harness.close_pipeline_issue(issue_number, "failed")
            await log_agent(self.name, "run_pipeline", "failed", str(e))

        return result
