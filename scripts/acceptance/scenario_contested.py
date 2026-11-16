import json

import httpx

c = httpx.Client(base_url="http://127.0.0.1:8765", timeout=600)
Q = (
    "Someone has a 6.5% fixed-rate mortgage and a spare $50,000. Should they pay down the "
    "mortgage or invest in a broad stock index fund? Choose one, give your reasoning in under "
    "150 words, and state how confident you are."
)
w = c.post(
    "/api/workspaces",
    json={
        "name": "E2E contested question",
        "delegates": ["groq", "openrouter-free", "qwen-flash", "deepseek-v3", "mistral", "gemini"],
        "arbiter": "groq",
        "arbiter_fallbacks": ["qwen-flash"],
        "critic": "qwen-flash",
        "critic_fallbacks": ["deepseek-v3"],
        "minimum_successes": 3,
        "single_source_mode": "return_answer",
    },
).json()["id"]
r = c.post(
    f"/api/workspaces/{w}/deliberate",
    json={"question": Q, "timeout_seconds": 90, "critic_timeout_seconds": 120, "arbiter_timeout_seconds": 120},
)
run_id = r.headers["X-Conclave-Run-ID"]
j = r.json()
run = c.get(f"/api/runs/{run_id}").json()
rows = c.get(f"/api/runs/{run_id}/calls").json()
out = {
    "run_id": run_id,
    "status": run["status"],
    "delegates": [
        {
            "name": d["name"],
            "status": d["status"],
            "kind": d["error_kind"],
            "model": d["model"],
            "latency_ms": d["latency_ms"],
            "attempts": d["attempts"],
            "raw_chars": len(d["raw_response"] or ""),
        }
        for d in j["panel"]["delegates"]
    ],
    "independent_sources": j["panel"]["independent_source_count"],
    "families": j["panel"]["distinct_families"],
    "quorum": j["panel"]["quorum"]["summary"],
    "positions": [
        {"label": p.get("label"), "conclusion": p.get("conclusion"), "confidence": p.get("confidence")}
        for p in j["positions"]
    ],
    "critic": {"name": j["critic"]["name"], "status": j["critic"]["status"]},
    "arbiter": {"name": j["arbiter"]["name"], "status": j["arbiter"]["status"]},
    "arbiter_sections_ok": j["arbiter_structure"]["format_ok"],
    "judge_overlaps": j["judge_overlaps"],
    "ledger": [
        {k: x[k] for k in ("stage", "provider", "outcome", "http_status", "prompt_tokens", "completion_tokens", "estimated_cost_usd", "reported_cost_usd")}
        for x in rows
    ],
    "cost": j["cost"],
    "arbiter_text": j["arbiter"]["raw_response"],
    "critic_text": j["critic"]["raw_response"],
}
# the blind-judging check on the real prompts that were sent
names = [d["name"] for d in j["panel"]["delegates"]] + ["groq", "qwen-flash", "deepseek-v3", "mistral", "gemini", "openrouter-free"]
models = [d["model"] for d in j["panel"]["delegates"] if d["model"]]
leaks = []
for stage in ("critic", "arbiter"):
    prompt = j[stage]["prompt"] or ""
    for token in set(names + models):
        if token and token.lower() in prompt.lower():
            leaks.append((stage, token))
out["identity_tokens_in_judge_prompts"] = leaks
json.dump(out, open("live4_out.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps({k: v for k, v in out.items() if k not in ("arbiter_text", "critic_text", "ledger")}, indent=1, ensure_ascii=False))
print("---ARBITER---")
print(out["arbiter_text"])
