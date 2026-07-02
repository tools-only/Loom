"""Wrapper: strip cc-switch proxy overrides so Brain reaches Anthropic via Veee HTTPS_PROXY."""
import os, sys

# Remove cc-switch routing — let SDK hit api.anthropic.com through Veee CONNECT tunnel
for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
    os.environ.pop(key, None)

# Ensure Veee proxy is set
os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:15236")

# Switch to loom/ so brain.py can do its relative imports
loom_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "loom")
os.chdir(loom_dir)
sys.path.insert(0, loom_dir)

import uvicorn
from brain import app
from harness.scheduler import setup_scheduler, shutdown_scheduler

from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(application):
    setup_scheduler()
    yield
    shutdown_scheduler()

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3002, log_level="info")
