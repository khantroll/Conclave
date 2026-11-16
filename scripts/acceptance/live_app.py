"""Usage: CONCLAVE_ACCEPTANCE_ENV=.env CONCLAVE_ACCEPTANCE_CONFIG=conclave.json python live_app.py <scratch dir>

Run the release-candidate app against real providers with a scratch database.

Keys come from the owner's existing env file (never copied or printed). The database and run
logs live in the scratchpad, so no real history is touched.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(os.environ["CONCLAVE_ACCEPTANCE_ENV"])  # a .env with your provider keys
SCRATCH = Path(sys.argv[1])
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["CONCLAVE_DB_PATH"] = str(SCRATCH / "live.db")
os.environ["CONCLAVE_RUN_LOG_DIR"] = str(SCRATCH / "run_logs")
os.environ["BADKEY_API_KEY"] = "invalid-key-for-failure-test"  # deliberately wrong, not a secret

import uvicorn  # noqa: E402

from conclave.api import create_app  # noqa: E402
from conclave.config import ConclaveConfig  # noqa: E402

raw = json.load(open(os.environ["CONCLAVE_ACCEPTANCE_CONFIG"], encoding="utf-8"))
by_name = {p["name"]: p for p in raw["providers"]}
extra = dict(by_name["groq"])
extra.update(name="badkey", model="llama-3.3-70b-versatile", api_key_env="BADKEY_API_KEY", transient_max_retries=0)
raw["providers"].append(extra)
# OpenRouter states cost in usage.cost: read it, so reported cost can be compared with the estimate.
for p in raw["providers"]:
    if "openrouter.ai" in p["base_url"]:
        p["reported_cost_field"] = "usage.cost"
    p.setdefault("transient_max_retries", 1)
config = ConclaveConfig.model_validate(raw)
app = create_app(config=config, load_env=False, allowed_hosts=["127.0.0.1", "localhost"])
uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
