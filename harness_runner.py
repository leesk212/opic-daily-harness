"""Harness Runner - Agent들을 독립 워커로 상시 실행 (Langfuse 트레이싱 포함)

각 Agent는 GitHub Issues를 감시하며 자기 차례가 오면 동작합니다.
Orchestrator가 주기적으로 파이프라인을 트리거하고,
나머지 Agent들은 Issue 댓글을 통해 상태를 주고받습니다.
모든 Agent 동작은 Langfuse로 트레이싱됩니다.
"""

import asyncio
import json
import time
import signal
import sys
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

from db import init_db, log_agent
from harness import GitHubHarness, ensure_labels, _gh, REPO
from tracing import create_pipeline_trace, start_span, start_generation, log_event, score_trace, flush as langfuse_flush
from agents.content_manager import ContentManagerAgent
from agents.question_generator import QuestionGeneratorAgent
from agents.delivery import DeliveryAgent

# 상태 공유 (Dashboard에서 조회용)
AGENT_STATUS = {
    "orchestrator": {"state": "idle", "last_run": None, "detail": ""},
    "content_manager": {"state": "idle", "last_run": None, "detail": ""},
    "question_generator": {"state": "idle", "last_run": None, "detail": ""},
    "delivery": {"state": "idle", "last_run": None, "detail": ""},
    "harness": {"state": "stopped", "started_at": None, "total_runs": 0, "loop_interval": 0},
}

harness = GitHubHarness()
shutdown_event = None  # run_harness()에서 초기화

# Issue별 Langfuse trace_id 관리
pipeline_trace_ids = {}  # {issue_number: trace_id}

# Trigger queue for orchestrator (scheduler/dashboard puts items here)
_trigger_queue: asyncio.Queue = None  # initialized in run_harness()


def trigger_pipeline():
    """외부(스케줄러/대시보드)에서 파이프라인 트리거.
    asyncio Queue에 아이템을 넣어 orchestrator_worker가 깨어남."""
    if _trigger_queue is not None:
        _trigger_queue.put_nowait("trigger")
        return True
    return False


def update_status(agent, state, detail=""):
    AGENT_STATUS[agent]["state"] = state
    AGENT_STATUS[agent]["last_run"] = datetime.now(KST).isoformat()
    AGENT_STATUS[agent]["detail"] = detail


def get_trace_id(issue_number):
    """Issue에 연결된 trace_id 반환 (없으면 생성)"""
    if issue_number not in pipeline_trace_ids:
        pipeline_trace_ids[issue_number] = create_pipeline_trace(issue_number)
    return pipeline_trace_ids[issue_number]


def find_pending_issues():
    try:
        output = _gh([
            "issue", "list", "--repo", REPO,
            "--label", "pipeline,status:in-progress",
            "--state", "open",
            "--json", "number,title,comments,createdAt",
            "--limit", "5",
        ])
        return json.loads(output) if output else []
    except Exception:
        return []


def issue_has_agent_comment(issue_number, agent_name):
    try:
        detail = harness.get_issue_detail(issue_number)
        for c in detail.get("comments", []):
            body = c.get("body", "")
            if f"Agent: `{agent_name}`" in body and ("success" in body or "failed" in body):
                return True
        return False
    except Exception:
        return False


def get_agent_data_from_comments(issue_number, agent_name):
    try:
        detail = harness.get_issue_detail(issue_number)
        for c in detail.get("comments", []):
            body = c.get("body", "")
            if f"Agent: `{agent_name}`" in body and "success" in body:
                if "```json" in body:
                    json_str = body.split("```json")[1].split("```")[0].strip()
                    json_str = json_str.replace("\\n", "\n")
                    return json.loads(json_str)
        return {}
    except Exception:
        return {}


# === Agent Workers ===

async def orchestrator_worker():
    """Trigger-based orchestrator: waits for items in _trigger_queue."""
    while not shutdown_event.is_set():
        update_status("orchestrator", "waiting", "Waiting for trigger (schedule or manual)...")
        try:
            # Wait for a trigger or shutdown
            done, pending = await asyncio.wait(
                [
                    asyncio.ensure_future(_trigger_queue.get()),
                    asyncio.ensure_future(shutdown_event.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Cancel pending futures
            for fut in pending:
                fut.cancel()
            # Check if shutdown was triggered
            if shutdown_event.is_set():
                break
        except Exception:
            if shutdown_event.is_set():
                break
            await asyncio.sleep(1)
            continue

        try:
            update_status("orchestrator", "running", "Creating new pipeline issue...")
            await log_agent("Orchestrator", "create_pipeline", "started")

            ensure_labels()
            issue_number = harness.create_pipeline_issue()

            # Langfuse: 파이프라인 trace 생성
            trace_id = create_pipeline_trace(issue_number)
            pipeline_trace_ids[issue_number] = trace_id
            span = start_span(trace_id, "orchestrator.create_pipeline", {"issue_number": issue_number})

            harness.post_agent_status(
                issue_number, "Orchestrator", "pipeline_start", "started",
                {"message": "Pipeline initiated. Waiting for agents..."},
            )

            span.end()
            AGENT_STATUS["harness"]["total_runs"] += 1
            update_status("orchestrator", "waiting", f"Issue #{issue_number} created, waiting for agents")
            await log_agent("Orchestrator", "create_pipeline", "success", f"issue #{issue_number}")
            langfuse_flush()

        except Exception as e:
            update_status("orchestrator", "error", str(e))
            await log_agent("Orchestrator", "create_pipeline", "failed", str(e))


async def content_manager_worker(poll_seconds=10):
    agent = ContentManagerAgent()

    while not shutdown_event.is_set():
        try:
            update_status("content_manager", "polling", "Scanning for new pipeline issues...")
            issues = find_pending_issues()

            for issue in issues:
                issue_num = issue["number"]
                if issue_has_agent_comment(issue_num, "ContentManager"):
                    continue

                update_status("content_manager", "running", f"Processing Issue #{issue_num}")
                await log_agent("ContentManager", "pick_topic", "started", f"issue #{issue_num}")

                # Langfuse: span
                trace_id = get_trace_id(issue_num)
                span = start_span(trace_id, "content_manager.pick_topic_and_type", {"issue_number": issue_num})

                harness.post_agent_status(issue_num, "ContentManager", "pick_topic_and_type", "started")
                selection = await agent.pick_topic_and_type()
                harness.post_agent_status(issue_num, "ContentManager", "pick_topic_and_type", "success", selection)

                span.end()
                update_status("content_manager", "done", f"Issue #{issue_num}: {selection['topic']}")
                await log_agent("ContentManager", "pick_topic", "success", str(selection))
                langfuse_flush()

        except Exception as e:
            update_status("content_manager", "error", str(e))
            await log_agent("ContentManager", "poll", "failed", str(e))

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=poll_seconds)
            break
        except asyncio.TimeoutError:
            pass


async def question_generator_worker(poll_seconds=15):
    agent = QuestionGeneratorAgent()

    while not shutdown_event.is_set():
        try:
            update_status("question_generator", "polling", "Waiting for ContentManager...")
            issues = find_pending_issues()

            for issue in issues:
                issue_num = issue["number"]
                if not issue_has_agent_comment(issue_num, "ContentManager"):
                    continue
                if issue_has_agent_comment(issue_num, "QuestionGenerator"):
                    continue

                update_status("question_generator", "running", f"Generating for Issue #{issue_num}")
                await log_agent("QuestionGenerator", "generate", "started", f"issue #{issue_num}")

                selection = get_agent_data_from_comments(issue_num, "ContentManager")
                topic = selection.get("topic", "자기소개")
                q_type = selection.get("question_type", "묘사 (Description)")

                # Langfuse: generation span (LLM 호출 추적)
                trace_id = get_trace_id(issue_num)
                generation = start_generation(
                    trace_id, "question_generator.claude_code",
                    model="claude-code-cli",
                    input_data={"topic": topic, "question_type": q_type},
                    metadata={"issue_number": issue_num, "target_level": "AL"},
                )

                harness.post_agent_status(
                    issue_num, "QuestionGenerator", "generate", "started",
                    {"topic": topic, "type": q_type},
                )

                question_data = await agent.generate(topic=topic, question_type=q_type)

                harness_data = {
                    "question_id": question_data.get("id"),
                    "question": question_data.get("question", ""),
                    "key_expressions": question_data.get("key_expressions", ""),
                    "tip": question_data.get("tip", ""),
                }
                harness.post_agent_status(
                    issue_num, "QuestionGenerator", "generate", "success", harness_data,
                )

                generation.end()
                update_status("question_generator", "done", f"Issue #{issue_num}: question generated")
                await log_agent("QuestionGenerator", "generate", "success", f"issue #{issue_num}")
                langfuse_flush()

        except Exception as e:
            update_status("question_generator", "error", str(e))
            await log_agent("QuestionGenerator", "poll", "failed", str(e))

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=poll_seconds)
            break
        except asyncio.TimeoutError:
            pass


async def delivery_worker(poll_seconds=10):
    agent = DeliveryAgent()

    while not shutdown_event.is_set():
        try:
            update_status("delivery", "polling", "Waiting for QuestionGenerator...")
            issues = find_pending_issues()

            for issue in issues:
                issue_num = issue["number"]
                if not issue_has_agent_comment(issue_num, "QuestionGenerator"):
                    continue
                if issue_has_agent_comment(issue_num, "Delivery"):
                    continue

                update_status("delivery", "running", f"Delivering Issue #{issue_num}")
                await log_agent("Delivery", "send", "started", f"issue #{issue_num}")

                q_data = get_agent_data_from_comments(issue_num, "QuestionGenerator")
                cm_data = get_agent_data_from_comments(issue_num, "ContentManager")
                q_data["topic"] = cm_data.get("topic", "Unknown")
                q_data["question_type"] = cm_data.get("question_type", "Unknown")
                q_data["id"] = q_data.get("question_id")

                # Langfuse: delivery span
                trace_id = get_trace_id(issue_num)
                span = start_span(trace_id, "delivery.slack_send", {"issue_number": issue_num, "topic": q_data["topic"]})

                harness.post_agent_status(issue_num, "Delivery", "send", "started")
                delivered = await agent.send(q_data)

                harness.post_agent_status(
                    issue_num, "Delivery", "send",
                    "success" if delivered else "failed",
                    {"delivered": delivered},
                )

                final_status = "success" if delivered else "failed"
                harness.post_agent_status(
                    issue_num, "Orchestrator", "pipeline_complete", final_status,
                    {"summary": f"Topic: {q_data['topic']}, Delivered: {delivered}"},
                )
                harness.close_pipeline_issue(issue_num, final_status)

                span.end()
                log_event(trace_id, "pipeline_result", output_data={"delivered": delivered, "status": final_status})

                # Langfuse: 최종 점수 기록
                score_trace(trace_id, "pipeline_success", 1.0 if delivered else 0.0, f"Topic: {q_data['topic']}")

                # 완료된 trace 정리
                pipeline_trace_ids.pop(issue_num, None)

                update_status("delivery", "done", f"Issue #{issue_num}: delivered={delivered}")
                await log_agent("Delivery", "send", "success" if delivered else "failed", f"issue #{issue_num}")
                langfuse_flush()

        except Exception as e:
            update_status("delivery", "error", str(e))
            await log_agent("Delivery", "poll", "failed", str(e))

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=poll_seconds)
            break
        except asyncio.TimeoutError:
            pass


async def run_harness():
    global shutdown_event, _trigger_queue
    shutdown_event = asyncio.Event()
    _trigger_queue = asyncio.Queue()
    await init_db()

    AGENT_STATUS["harness"]["state"] = "running"
    AGENT_STATUS["harness"]["started_at"] = datetime.now(KST).isoformat()
    AGENT_STATUS["harness"]["loop_interval"] = 0  # trigger-based, no fixed interval

    print(f"{'='*60}")
    print(f"  OPIC Daily Harness - RUNNING (trigger-based)")
    print(f"  Schedule: 06:00, 12:00, 18:00, 00:00 KST")
    print(f"  Agents: Orchestrator, ContentManager, QuestionGenerator, Delivery")
    print(f"  GitHub: https://github.com/{REPO}/issues")
    print(f"  Langfuse: https://cloud.langfuse.com")
    print(f"{'='*60}")

    tasks = [
        asyncio.create_task(orchestrator_worker()),
        asyncio.create_task(content_manager_worker(poll_seconds=10)),
        asyncio.create_task(question_generator_worker(poll_seconds=15)),
        asyncio.create_task(delivery_worker(poll_seconds=10)),
    ]

    def handle_signal(*_):
        print("\nShutting down harness...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    await asyncio.gather(*tasks)
    langfuse_flush()
    AGENT_STATUS["harness"]["state"] = "stopped"
    print("Harness stopped.")


if __name__ == "__main__":
    asyncio.run(run_harness())
