import json
import time

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8765", timeout=400)
Q = "In one sentence each: what is the main advantage and the main risk of a monorepo?"
OUT = {}


def calls(run_id):
    return c.get(f"/api/runs/{run_id}/calls").json()


def summary(r):
    j = r.json()
    run_id = r.headers.get("X-Conclave-Run-ID")
    p = j["panel"]
    rows = calls(run_id)
    return {
        "http": r.status_code,
        "delegates": [(d["name"], d["status"], d["error_kind"]) for d in p["delegates"]],
        "arbiter": j["arbiter"] and (j["arbiter"]["name"], j["arbiter"]["status"], j["arbiter"]["error_kind"]),
        "stopped": j["stopped_reason"],
        "ledger_rows": len(rows),
        "ledger_estimated": round(sum(x["estimated_cost_usd"] or 0 for x in rows), 8),
        "ledger_reported": [x["reported_cost_usd"] for x in rows],
        "result_cost": j["estimated_cost_usd"],
    }


base = {
    "question": Q,
    "delegates": ["qwen-flash", "deepseek-v3"],
    "arbiter": "qwen-flash",
    "minimum_successes": 1,
    "single_source_mode": "arbiter_single_source",
    "timeout_seconds": 120,
    "arbiter_timeout_seconds": 120,
}

# C1: ceiling too small for any call
r = c.post("/api/deliberate", json={**base, "max_estimated_cost_usd": 0.0001})
OUT["C1_tiny_ceiling"] = summary(r)
# C2: roomy ceiling
r = c.post("/api/deliberate", json={**base, "max_estimated_cost_usd": 0.05})
OUT["C2_roomy_ceiling"] = summary(r)
# C3: room for one delegate, not both
r = c.post("/api/deliberate", json={**base, "max_estimated_cost_usd": 0.005})
OUT["C3_partial_ceiling"] = summary(r)
# C4: unbounded provider refused up front
r = c.post("/api/deliberate", json={**base, "delegates": ["demo-a"], "max_estimated_cost_usd": 1})
OUT["C4_preflight"] = {"http": r.status_code, "detail": r.json()["detail"][:200]}

# E: background run, cancel, then prove no further calls happen
r = c.post(
    "/api/deliberate?background=true",
    json={**base, "delegates": ["deepseek-v3", "qwen-flash"], "arbiter": "deepseek-v3"},
)
run_id = r.json()["run_id"]
time.sleep(1.5)
t0 = time.time()
cancel = c.post(f"/api/runs/{run_id}/cancel")
status = c.get(f"/api/runs/{run_id}").json()["status"]
n1 = len(calls(run_id))
time.sleep(8)
n2 = len(calls(run_id))
OUT["E_background_cancel"] = {
    "start_http": r.status_code,
    "cancel_http": cancel.status_code,
    "cancel_seconds": round(time.time() - t0 - 8, 2),
    "status_after_cancel": status,
    "ledger_rows_right_after": n1,
    "ledger_rows_8s_later": n2,
    "second_cancel_http": c.post(f"/api/runs/{run_id}/cancel").status_code,
    "background_list": c.get("/api/dashboard").json()["running_in_background"],
}

# F: shared stage deadline, 0.3 s per stage so every attempt times out
f_base = {
    "question": Q,
    "delegates": ["qwen-flash"],
    "arbiter": "deepseek-v3",
    "arbiter_fallbacks": ["qwen-flash", "groq"],
    "minimum_successes": 1,
    "single_source_mode": "arbiter_single_source",
    "timeout_seconds": 120,
    "arbiter_timeout_seconds": 0.3,
}
for label, shared in (("F_default", False), ("F_shared", True)):
    r = c.post("/api/deliberate", json={**f_base, "shared_stage_deadline": shared})
    rows = [x for x in calls(r.headers["X-Conclave-Run-ID"]) if x["stage"] == "arbiter"]
    OUT[label] = {
        "arbiter_ledger_rows": [(x["provider"], x["outcome"]) for x in rows],
        "arbiter_result": (r.json()["arbiter"]["name"], r.json()["arbiter"]["status"]),
        "prior_attempts": [a["name"] for a in r.json()["arbiter"]["prior_attempts"]],
    }

json.dump(OUT, open("live3_out.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(OUT, indent=1, ensure_ascii=False))
