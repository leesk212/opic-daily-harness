"""Dashboard - FastAPI 웹 서버 (GitHub Issues Harness 연동)"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from db import init_db, get_all_questions, get_delivery_logs, get_agent_logs, get_stats
from harness import GitHubHarness
from config import load_kakao_recipients, save_kakao_recipients, load_selected_topics, save_selected_topics, OPIC_TOPICS

app = FastAPI(title="OPIC Agent Dashboard")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
gh_harness = GitHubHarness()


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/stats")
async def api_stats():
    return await get_stats()


@app.get("/api/questions")
async def api_questions():
    rows = await get_all_questions(limit=50)
    return [dict(r) for r in rows]


@app.get("/api/delivery-logs")
async def api_delivery_logs():
    rows = await get_delivery_logs(limit=50)
    return [dict(r) for r in rows]


@app.get("/api/agent-logs")
async def api_agent_logs():
    rows = await get_agent_logs(limit=100)
    return [dict(r) for r in rows]


@app.get("/api/pipelines")
async def api_pipelines():
    return gh_harness.get_pipeline_issues(state="all", limit=20)


@app.get("/api/pipelines/{issue_number}")
async def api_pipeline_detail(issue_number: int):
    return gh_harness.get_issue_detail(issue_number)


@app.get("/api/harness-status")
async def api_harness_status():
    """실시간 Agent 상태 (harness_runner에서 import)"""
    try:
        from harness_runner import AGENT_STATUS
        return AGENT_STATUS
    except Exception:
        return {"harness": {"state": "not_running"}}


@app.post("/api/trigger")
async def api_trigger():
    """수동 파이프라인 트리거"""
    try:
        from harness_runner import trigger_pipeline
        ok = trigger_pipeline()
        if ok:
            return {"status": "triggered", "message": "Pipeline trigger queued."}
        else:
            return {"status": "error", "message": "Harness is not running."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/shutdown")
async def api_shutdown():
    """Agent만 중지 (Dashboard + Scheduler는 유지)"""
    try:
        from harness_runner import shutdown_harness
        ok = shutdown_harness()
        if ok:
            return {"status": "shutdown", "message": "All agents stopped. Dashboard is still running."}
        else:
            return {"status": "error", "message": "Harness is not running."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/restart")
async def api_restart():
    """Agent 재시작"""
    try:
        import run as run_module
        ok = run_module.start_harness()
        if ok:
            return {"status": "started", "message": "Harness restarted. Agents are running."}
        else:
            return {"status": "error", "message": "Harness is already running."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/schedule")
async def api_schedule():
    """다음 예정 스케줄 목록 반환"""
    from datetime import datetime, timezone, timedelta
    from config import SCHEDULE_HOURS

    KST = timezone(timedelta(hours=9))
    now = datetime.now(KST)
    today = now.date()

    schedules = []
    for h in sorted(SCHEDULE_HOURS):
        t = datetime(today.year, today.month, today.day, h, 0, tzinfo=KST)
        if t <= now:
            # 다음날로
            t += timedelta(days=1)
        schedules.append({
            "time": t.strftime("%Y-%m-%d %H:%M KST"),
            "hour": h,
            "remaining_minutes": int((t - now).total_seconds() / 60),
        })

    schedules.sort(key=lambda x: x["remaining_minutes"])

    return {
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S KST"),
        "schedule_hours": SCHEDULE_HOURS,
        "next_runs": schedules,
    }


@app.get("/api/topics")
async def api_get_topics():
    return {"all_topics": OPIC_TOPICS, "selected": load_selected_topics()}


@app.put("/api/topics")
async def api_set_topics(request: Request):
    data = await request.json()
    selected = data if isinstance(data, list) else data.get("selected", [])
    invalid = [t for t in selected if t not in OPIC_TOPICS]
    if invalid:
        return {"status": "error", "message": f"Invalid topics: {invalid}"}
    if len(selected) != 12:
        return {"status": "error", "message": f"Exactly 12 topics required, got {len(selected)}"}
    save_selected_topics(selected)
    return {"status": "ok", "selected": selected}


@app.get("/api/recipients")
async def api_get_recipients():
    return load_kakao_recipients()


@app.put("/api/recipients")
async def api_set_recipients(request: Request):
    """수신자 목록 업데이트"""
    recipients = await request.json()
    if not isinstance(recipients, list):
        return {"status": "error", "message": "recipients must be a list"}
    for r in recipients:
        if "name" not in r or "self" not in r:
            return {"status": "error", "message": "each recipient needs 'name' and 'self' fields"}
    save_kakao_recipients(recipients)
    return {"status": "ok", "recipients": recipients}
