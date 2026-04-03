"""OPIC Daily Agent Harness - 메인 실행 파일

Usage:
    python run.py                    # Harness + Dashboard + Scheduler 실행
    python run.py --dashboard        # Dashboard만 실행
    python run.py --run-now          # 즉시 1회 트리거 후 스케줄 모드

Schedule: 06:00, 12:00, 18:00, 00:00 KST
Manual trigger: POST /api/trigger
"""

import asyncio
import sys
import threading
import uvicorn

from config import DASHBOARD_PORT, SCHEDULE_HOURS


def start_dashboard():
    """별도 스레드에서 Dashboard 실행"""
    uvicorn.run(
        "dashboard.app:app",
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        log_level="warning",
    )


def start_scheduler():
    """APScheduler로 KST 기준 정해진 시각에 파이프라인 트리거"""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from datetime import timezone, timedelta

    KST = timezone(timedelta(hours=9))

    def _trigger():
        from harness_runner import trigger_pipeline
        trigger_pipeline()

    scheduler = BackgroundScheduler()

    # Schedule at each configured hour (KST)
    hours_csv = ",".join(str(h) for h in SCHEDULE_HOURS)
    scheduler.add_job(
        _trigger,
        CronTrigger(hour=hours_csv, minute=0, timezone=KST),
        id="opic_daily_pipeline",
        name=f"OPIC Pipeline @ {hours_csv}:00 KST",
        replace_existing=True,
    )

    scheduler.start()
    print(f"  Scheduler: Pipeline at {hours_csv}:00 KST")
    return scheduler


def main():
    if "--dashboard" in sys.argv:
        print(f"Dashboard only: http://localhost:{DASHBOARD_PORT}")
        uvicorn.run("dashboard.app:app", host="0.0.0.0", port=DASHBOARD_PORT, reload=True)
        return

    run_now = "--run-now" in sys.argv

    # Dashboard를 별도 스레드에서 실행
    dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
    dashboard_thread.start()
    print(f"  Dashboard: http://localhost:{DASHBOARD_PORT}")

    # Harness 메인 루프 실행 (trigger-based)
    from harness_runner import run_harness, trigger_pipeline

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # run_harness를 시작하되, 먼저 큐 초기화가 완료되어야 scheduler가 작동함
    harness_task = loop.create_task(run_harness())

    # Scheduler 시작 (harness 이벤트 루프가 돌고 있어야 trigger_pipeline이 동작)
    scheduler = start_scheduler()

    if run_now:
        # 즉시 1회 트리거
        loop.call_soon(trigger_pipeline)
        print("  Immediate trigger queued.")

    try:
        loop.run_until_complete(harness_task)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        scheduler.shutdown(wait=False)
        loop.close()


if __name__ == "__main__":
    main()
