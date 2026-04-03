"""GitHub Issues Harness - Agent 간 통신 레이어

각 Agent는 GitHub Issue와 댓글을 통해 상태를 주고받습니다.
하나의 파이프라인 실행 = 하나의 Issue
각 Agent의 실행 결과 = 해당 Issue의 댓글
"""

import json
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

KST = timezone(timedelta(hours=9))


REPO = "leesk212/opic-daily-harness"

LABELS = {
    "orchestrator": "agent:orchestrator",
    "content_manager": "agent:content-manager",
    "question_generator": "agent:question-generator",
    "delivery": "agent:delivery",
    "pipeline": "pipeline",
    "success": "status:success",
    "failed": "status:failed",
    "in_progress": "status:in-progress",
}


def _gh(args: List[str], input_text: Optional[str] = None) -> str:
    """gh CLI 래퍼"""
    cmd = ["gh"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=input_text,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh command failed: {result.stderr}")
    return result.stdout.strip()


def ensure_labels():
    """필요한 라벨이 없으면 생성"""
    existing = _gh(["label", "list", "--repo", REPO, "--json", "name", "-q", ".[].name"])
    existing_labels = set(existing.split("\n")) if existing else set()

    label_colors = {
        "agent:orchestrator": "5319E7",
        "agent:content-manager": "0E8A16",
        "agent:question-generator": "1D76DB",
        "agent:delivery": "D93F0B",
        "pipeline": "FBCA04",
        "status:success": "0E8A16",
        "status:failed": "B60205",
        "status:in-progress": "FEF2C0",
    }

    for label, color in label_colors.items():
        if label not in existing_labels:
            try:
                _gh(["label", "create", label, "--repo", REPO, "--color", color, "--force"])
            except RuntimeError:
                pass  # label may already exist


class GitHubHarness:
    """GitHub Issues 기반 Agent 통신 harness"""

    def __init__(self):
        self.repo = REPO

    def create_pipeline_issue(self) -> int:
        """새 파이프라인 실행용 Issue 생성 → Issue 번호 반환"""
        today = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        title = f"[Pipeline] OPIC Daily - {today} KST"
        body = json.dumps({
            "type": "pipeline_start",
            "agent": "orchestrator",
            "timestamp": today,
            "status": "in_progress",
        }, ensure_ascii=False, indent=2)

        output = _gh([
            "issue", "create",
            "--repo", self.repo,
            "--title", title,
            "--body", body,
            "--label", f"{LABELS['pipeline']},{LABELS['orchestrator']},{LABELS['in_progress']}",
        ])
        # output: "https://github.com/.../issues/1"
        issue_number = int(output.rstrip("/").split("/")[-1])
        return issue_number

    def post_agent_status(self, issue_number: int, agent_name: str, action: str, status: str, data: Optional[Dict] = None):
        """Agent 실행 결과를 Issue 댓글로 기록"""
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
        payload = {
            "agent": agent_name,
            "action": action,
            "status": status,
            "timestamp": timestamp,
        }
        if data:
            payload["data"] = data

        # Agent별 이모지
        agent_emoji = {
            "Orchestrator": "\U0001f3af",
            "ContentManager": "\U0001f4cb",
            "QuestionGenerator": "\U0001f916",
            "Delivery": "\U0001f4e8",
        }.get(agent_name, "\u2139\ufe0f")

        # Agent별 라벨
        agent_label = {
            "Orchestrator": "agent:orchestrator",
            "ContentManager": "agent:content-manager",
            "QuestionGenerator": "agent:question-generator",
            "Delivery": "agent:delivery",
        }.get(agent_name, "")

        # 마크다운 포맷 댓글
        status_emoji = {"success": "\u2705", "failed": "\u274c", "started": "\U0001f504", "in_progress": "\u23f3"}.get(status, "\u2139\ufe0f")

        body_lines = [
            f"## {agent_emoji} {status_emoji} Agent: `{agent_name}` — {action}",
            f"**Label:** `{agent_label}` | **Status:** `{status}` | **Time:** `{timestamp}`",
            "",
        ]

        if data:
            body_lines.append("### Payload")
            body_lines.append("```json")
            body_lines.append(json.dumps(data, ensure_ascii=False, indent=2))
            body_lines.append("```")

        body = "\n".join(body_lines)

        _gh([
            "issue", "comment",
            "--repo", self.repo,
            str(issue_number),
            "--body", body,
        ])

    def close_pipeline_issue(self, issue_number: int, status: str):
        """파이프라인 완료 시 Issue 닫기 + 라벨 업데이트"""
        label = LABELS.get(status, LABELS["success"])

        # in_progress 라벨 제거, 최종 상태 라벨 추가
        try:
            _gh(["issue", "edit", "--repo", self.repo, str(issue_number),
                 "--remove-label", LABELS["in_progress"]])
        except RuntimeError:
            pass

        _gh(["issue", "edit", "--repo", self.repo, str(issue_number),
             "--add-label", label])

        state_reason = "completed" if status == "success" else "not planned"
        _gh(["issue", "close", "--repo", self.repo, str(issue_number),
             "--reason", state_reason])

    def get_pipeline_issues(self, state: str = "all", limit: int = 20) -> List[Dict]:
        """파이프라인 Issue 목록 조회"""
        output = _gh([
            "issue", "list",
            "--repo", self.repo,
            "--label", LABELS["pipeline"],
            "--state", state,
            "--limit", str(limit),
            "--json", "number,title,state,labels,createdAt,closedAt,comments",
        ])
        return json.loads(output) if output else []

    def get_issue_comments(self, issue_number: int) -> List[Dict]:
        """특정 Issue의 댓글(Agent 상태) 조회"""
        output = _gh([
            "issue", "view",
            "--repo", self.repo,
            str(issue_number),
            "--json", "comments",
        ])
        data = json.loads(output) if output else {}
        return data.get("comments", [])

    def get_issue_detail(self, issue_number: int) -> dict:
        """Issue 상세 정보"""
        output = _gh([
            "issue", "view",
            "--repo", self.repo,
            str(issue_number),
            "--json", "number,title,state,body,labels,createdAt,closedAt,comments",
        ])
        return json.loads(output) if output else {}
