import json

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8765", timeout=400)
Q = (
    "A five-person team is building an internal CRUD web app that may later split into a few "
    "services. Should it use one monorepo or separate repositories? Give a firm recommendation "
    "in under 120 words and name the one risk you consider most important."
)
OUT = {}


def brief(result):
    p = result["panel"]
    return {
        "delegates": [
            {
                "name": d["name"],
                "status": d["status"],
                "kind": d["error_kind"],
                "reserve": d.get("reserve"),
                "model": d["model"],
                "chars": len(d["raw_response"] or ""),
            }
            for d in p["delegates"]
        ],
        "independent_sources": p["independent_source_count"],
        "quorum": p["quorum"]["status"],
        "critic": result["critic"] and result["critic"]["status"],
        "arbiter": result["arbiter"] and (result["arbiter"]["name"], result["arbiter"]["status"]),
        "positions": [(x.get("label"), (x.get("conclusion") or "")[:90]) for x in result["positions"]],
        "format_ok": result["arbiter_structure"] and result["arbiter_structure"]["format_ok"],
        "est_cost": result["estimated_cost_usd"],
        "cost": result["cost"],
        "stopped": result["stopped_reason"],
    }


def ws(name, **kw):
    body = {
        "name": name,
        "delegates": ["groq", "openrouter-free", "qwen-flash", "deepseek-v3", "badkey"],
        "arbiter": "groq",
        "arbiter_fallbacks": ["qwen-flash"],
        "critic": None,
        "minimum_successes": 2,
        "single_source_mode": "return_answer",
    }
    body.update(kw)
    r = c.post("/api/workspaces", json=body)
    r.raise_for_status()
    return r.json()["id"]


# A: partial failure, no Critic
w = ws("A partial failure")
r = c.post(f"/api/workspaces/{w}/deliberate", json={"question": Q, "timeout_seconds": 120, "critic_timeout_seconds": 120, "arbiter_timeout_seconds": 120})
run_a = r.headers["X-Conclave-Run-ID"]
OUT["A"] = brief(r.json())
OUT["A_final_text"] = ((r.json()["arbiter"] or {}).get("raw_response") or "")[:1500]

# B: explicit Critic
w = ws("B critic", critic="qwen-flash", critic_fallbacks=["deepseek-v3"])
r = c.post(f"/api/workspaces/{w}/deliberate", json={"question": Q, "timeout_seconds": 120, "critic_timeout_seconds": 120, "arbiter_timeout_seconds": 120})
OUT["B"] = brief(r.json())

# D: reserve wave: quorum 2, one delegate bad, reserve answers
w = ws("D reserve", delegates=["badkey", "groq"], minimum_successes=2)
r = c.post(f"/api/workspaces/{w}/deliberate", json={"question": Q, "timeout_seconds": 120, "critic_timeout_seconds": 120, "arbiter_timeout_seconds": 120})
OUT["D_without_reserve"] = brief(r.json()) if r.status_code == 200 else {"http": r.status_code, "detail": r.json()}
w = ws(
    "D2 reserve",
    delegates=["badkey", "groq", "qwen-flash", "deepseek-v3"],
    minimum_successes=2,
    auto_select_delegates=False,
)
r = c.post(
    "/api/deliberate",
    json={
        "question": Q,
        "delegates": ["badkey", "groq"],
        "reserve_delegates": ["qwen-flash", "deepseek-v3"],
        "minimum_successes": 2,
        "arbiter": "groq",
        "arbiter_fallbacks": ["qwen-flash"],
    },
)
OUT["D_with_reserve"] = brief(r.json())

json.dump(OUT, open("live2_out.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(OUT, indent=1, ensure_ascii=False)[:9000])
print("run A:", run_a)
