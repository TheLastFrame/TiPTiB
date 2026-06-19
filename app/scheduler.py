from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.database import SessionLocal
from app.services import process_due_savings_rules

scheduler: BackgroundScheduler | None = None


def run_due_rules() -> None:
    db = SessionLocal()
    try:
        process_due_savings_rules(db)
    finally:
        db.close()


def start_scheduler() -> None:
    global scheduler
    settings = get_settings()
    if not settings.scheduler_enabled or scheduler:
        return
    scheduler = BackgroundScheduler(timezone=settings.default_timezone)
    scheduler.add_job(run_due_rules, "interval", minutes=15, id="due_savings_rules", replace_existing=True)
    scheduler.start()


def stop_scheduler() -> None:
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        scheduler = None
