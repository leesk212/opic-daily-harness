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
import time
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


def run_harness_in_thread():
    """Harness를 별도 스레드에서 실행. 종료되어도 스레드만 끝남."""
    from harness_runner import run_harness
    try:
        asyncio.run(run_harness())
    except Exception as e:
        print(f"  Harness stopped: {e}")
    print("  Harness thread exited.")


# 글로벌 harness 스레드 참조 (재시작용)
_harness_thread = None


def start_harness():
    """Harness 스레드 시작"""
    global _harness_thread
    if _harness_thread and _harness_thread.is_alive():
        return False  # 이미 실행 중
    _harness_thread = threading.Thread(target=run_harness_in_thread, daemon=True)
    _harness_thread.start()
    return True


def is_harness_alive():
    return _harness_thread is not None and _harness_thread.is_alive()


def main():
    if "--dashboard" in sys.argv:
        print(f"Dashboard only: http://localhost:{DASHBOARD_PORT}")
        uvicorn.run("dashboard.app:app", host="0.0.0.0", port=DASHBOARD_PORT, reload=True)
        return

    run_now = "--run-now" in sys.argv

    # 1. Dashboard (별도 스레드)
    dashboard_thread = threading.Thread(target=start_dashboard, daemon=True)
    dashboard_thread.start()
    print(f"  Dashboard: http://localhost:{DASHBOARD_PORT}")

    # 2. Harness (별도 스레드 - 종료되어도 메인은 안 죽음)
    start_harness()
    time.sleep(1)  # queue 초기화 대기

    # 3. Scheduler (백그라운드)
    scheduler = start_scheduler()

    if run_now:
        time.sleep(1)
        from harness_runner import trigger_pipeline
        trigger_pipeline()
        print("  Immediate trigger queued.")

    # 메인 스레드: Ctrl+C 대기 (Dashboard + Scheduler는 계속 동작)
    print(f"\n  Running. Press Ctrl+C to exit completely.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down everything...")
        from harness_runner import shutdown_harness
        shutdown_harness()
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
