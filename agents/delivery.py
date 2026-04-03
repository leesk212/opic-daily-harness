"""Delivery Agent - KakaoTalk으로 OPIC 문제 전송 (kakaocli 사용)"""

import subprocess
import time
from config import KAKAOCLI_PATH, load_kakao_recipients
from db import save_delivery, log_agent


class DeliveryAgent:
    name = "Delivery"

    def _format_messages(self, question_data: dict) -> list:
        """메시지를 2개로 분할: 문제 + 답안 (카카오톡 UI 자동화 안정성)"""
        q = question_data

        msg1 = "\n".join([
            "━━━━━━━━━━━━━━━━━━━━",
            "OPIC Daily Practice",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
            f"Topic: {q.get('topic', 'N/A')}",
            f"Type: {q.get('question_type', 'N/A')}",
            f"Level: AL",
            "",
            "──────────────────",
            "Question:",
            q.get('question', 'N/A'),
            "──────────────────",
            "",
            "Key Expressions:",
            q.get('key_expressions', 'N/A'),
            "",
            "Tip:",
            q.get('tip', ''),
        ])

        msg2 = "\n".join([
            "──────────────────",
            "Sample Answer:",
            "(먼저 직접 답해보세요!)",
            "",
            q.get('sample_answer', 'N/A'),
            "━━━━━━━━━━━━━━━━━━━━",
        ])

        return [msg1, msg2]

    def _send_kakaotalk(self, recipient: dict, message: str) -> None:
        if recipient.get("self"):
            cmd = [KAKAOCLI_PATH, "send", "--me", "_", message]
        else:
            cmd = [KAKAOCLI_PATH, "send", recipient["name"], message]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"kakaocli failed ({recipient['name']}): {result.stderr or result.stdout}")

    async def send(self, question_data: dict) -> dict:
        """전송 후 수신자별 결과를 dict로 반환."""
        await log_agent(self.name, "send", "started", f"question_id={question_data.get('id')}")

        results = []
        all_ok = True
        for recipient in load_kakao_recipients():
            channel = f"kakaotalk:{recipient['name']}"
            try:
                messages = self._format_messages(question_data)
                for msg in messages:
                    self._send_kakaotalk(recipient, msg)
                    time.sleep(2)

                await save_delivery(
                    question_id=question_data.get("id"),
                    channel=channel,
                    status="success",
                )
                await log_agent(self.name, "send", "success", f"sent to {recipient['name']}")
                results.append({"recipient": recipient["name"], "status": "success"})

            except Exception as e:
                all_ok = False
                await save_delivery(
                    question_id=question_data.get("id"),
                    channel=channel,
                    status="failed",
                    error_message=str(e),
                )
                await log_agent(self.name, "send", "failed", f"{recipient['name']}: {e}")
                results.append({"recipient": recipient["name"], "status": "failed", "error": str(e)})

        return {"delivered": all_ok, "recipients": results}
