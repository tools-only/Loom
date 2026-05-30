"""Entry point — starts the Loom Brain FastAPI service + APScheduler."""
import uvicorn
from brain import app
from harness.scheduler import setup_scheduler, shutdown_scheduler

if __name__ == "__main__":
    scheduler = setup_scheduler()
    try:
        uvicorn.run(app, host="127.0.0.1", port=3001, log_level="info")
    finally:
        shutdown_scheduler()
