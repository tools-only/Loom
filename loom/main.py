"""Entry point — starts the Loom Brain FastAPI service + APScheduler."""
from contextlib import asynccontextmanager
import uvicorn
from brain import app
from harness.scheduler import setup_scheduler, shutdown_scheduler


@asynccontextmanager
async def lifespan(application):
    setup_scheduler()
    yield
    shutdown_scheduler()


app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3002, log_level="info")
