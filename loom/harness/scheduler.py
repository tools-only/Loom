"""APScheduler — daily harness review at 07:00 ET, weekdays."""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .review import run_daily_review

_scheduler: AsyncIOScheduler | None = None


def setup_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_daily_review,
        trigger="cron",
        hour=7,
        minute=0,
        day_of_week="mon-fri",
        timezone="America/New_York",
        id="daily_review",
        replace_existing=True,
    )
    _scheduler.start()
    return _scheduler


def shutdown_scheduler():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
