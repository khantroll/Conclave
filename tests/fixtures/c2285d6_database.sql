BEGIN TRANSACTION;
CREATE TABLE deliberation_runs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT,
                    question TEXT NOT NULL,
                    request_json TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
                );
INSERT INTO "deliberation_runs" VALUES('a0639b74-1139-4a34-9c2e-f9f09461440c','43996cb1-f0e4-45a5-8a47-8a42d040bc7b','Legacy question 1','{"question":"Legacy question 1","delegates":["demo-a","demo-b"],"arbiter":"demo-a","arbiter_fallbacks":[],"critic":"demo-critic","critic_fallbacks":[],"roles":{},"workspace_context":null,"minimum_successes":2,"timeout_seconds":60.0,"critic_timeout_seconds":60.0,"arbiter_timeout_seconds":90.0}','{"panel":{"question":"Legacy question 1","delegates":[{"name":"demo-a","status":"succeeded","prompt":"p","raw_response":"answer 1 a","model":"m1","error":null,"latency_ms":5,"usage":{},"estimated_cost_usd":null,"attempts":1},{"name":"demo-b","status":"succeeded","prompt":"p","raw_response":"answer 1 b","model":"m2","error":null,"latency_ms":6,"usage":{},"estimated_cost_usd":null,"attempts":1}],"successful_count":2,"failed_count":0,"synthesizeable":true},"critic":{"name":"demo-critic","status":"succeeded","prompt":null,"raw_response":"crit","model":null,"error":null,"latency_ms":null,"usage":{},"estimated_cost_usd":null,"attempts":1},"arbiter":{"name":"demo-a","status":"succeeded","prompt":null,"raw_response":"final","model":null,"error":null,"latency_ms":null,"usage":{},"estimated_cost_usd":null,"attempts":1},"estimated_cost_usd":0.001}','2026-11-13T14:14:16.590325+00:00');
INSERT INTO "deliberation_runs" VALUES('01291106-b114-4aa1-8ca0-1ecd1a547182','43996cb1-f0e4-45a5-8a47-8a42d040bc7b','Legacy question 2','{"question":"Legacy question 2","delegates":["demo-a","demo-b"],"arbiter":"demo-a","arbiter_fallbacks":[],"critic":"demo-critic","critic_fallbacks":[],"roles":{},"workspace_context":null,"minimum_successes":2,"timeout_seconds":60.0,"critic_timeout_seconds":60.0,"arbiter_timeout_seconds":90.0}','{"panel":{"question":"Legacy question 2","delegates":[{"name":"demo-a","status":"succeeded","prompt":"p","raw_response":"answer 2 a","model":"m1","error":null,"latency_ms":5,"usage":{},"estimated_cost_usd":null,"attempts":1},{"name":"demo-b","status":"succeeded","prompt":"p","raw_response":"answer 2 b","model":"m2","error":null,"latency_ms":6,"usage":{},"estimated_cost_usd":null,"attempts":1}],"successful_count":2,"failed_count":0,"synthesizeable":true},"critic":{"name":"demo-critic","status":"succeeded","prompt":null,"raw_response":"crit","model":null,"error":null,"latency_ms":null,"usage":{},"estimated_cost_usd":null,"attempts":1},"arbiter":{"name":"demo-a","status":"succeeded","prompt":null,"raw_response":"final","model":null,"error":null,"latency_ms":null,"usage":{},"estimated_cost_usd":null,"attempts":1},"estimated_cost_usd":0.002}','2026-11-13T14:14:16.598987+00:00');
INSERT INTO "deliberation_runs" VALUES('a339410a-30aa-420c-9bea-3625e5ce2f6d','43996cb1-f0e4-45a5-8a47-8a42d040bc7b','Legacy question 3','{"question":"Legacy question 3","delegates":["demo-a","demo-b"],"arbiter":"demo-a","arbiter_fallbacks":[],"critic":"demo-critic","critic_fallbacks":[],"roles":{},"workspace_context":null,"minimum_successes":2,"timeout_seconds":60.0,"critic_timeout_seconds":60.0,"arbiter_timeout_seconds":90.0}','{"panel":{"question":"Legacy question 3","delegates":[{"name":"demo-a","status":"succeeded","prompt":"p","raw_response":"answer 3 a","model":"m1","error":null,"latency_ms":5,"usage":{},"estimated_cost_usd":null,"attempts":1},{"name":"demo-b","status":"succeeded","prompt":"p","raw_response":"answer 3 b","model":"m2","error":null,"latency_ms":6,"usage":{},"estimated_cost_usd":null,"attempts":1}],"successful_count":2,"failed_count":0,"synthesizeable":true},"critic":{"name":"demo-critic","status":"succeeded","prompt":null,"raw_response":"crit","model":null,"error":null,"latency_ms":null,"usage":{},"estimated_cost_usd":null,"attempts":1},"arbiter":{"name":"demo-a","status":"succeeded","prompt":null,"raw_response":"final","model":null,"error":null,"latency_ms":null,"usage":{},"estimated_cost_usd":null,"attempts":1},"estimated_cost_usd":0.003}','2026-11-13T14:14:16.606739+00:00');
INSERT INTO "deliberation_runs" VALUES('fac126e1-7bff-4bfb-ae2e-2bddd4635523',NULL,'Detached legacy run',NULL,'{"panel":{"question":"Legacy question 9","delegates":[{"name":"demo-a","status":"succeeded","prompt":"p","raw_response":"answer 9 a","model":"m1","error":null,"latency_ms":5,"usage":{},"estimated_cost_usd":null,"attempts":1},{"name":"demo-b","status":"succeeded","prompt":"p","raw_response":"answer 9 b","model":"m2","error":null,"latency_ms":6,"usage":{},"estimated_cost_usd":null,"attempts":1}],"successful_count":2,"failed_count":0,"synthesizeable":true},"critic":{"name":"demo-critic","status":"succeeded","prompt":null,"raw_response":"crit","model":null,"error":null,"latency_ms":null,"usage":{},"estimated_cost_usd":null,"attempts":1},"arbiter":{"name":"demo-a","status":"succeeded","prompt":null,"raw_response":"final","model":null,"error":null,"latency_ms":null,"usage":{},"estimated_cost_usd":null,"attempts":1},"estimated_cost_usd":0.009000000000000001}','2026-11-13T14:14:16.612040+00:00');
CREATE TABLE workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    context TEXT,
                    delegates_json TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    critic TEXT,
                    critic_fallbacks_json TEXT NOT NULL DEFAULT '[]',
                    arbiter TEXT NOT NULL,
                    arbiter_fallbacks_json TEXT NOT NULL DEFAULT '[]',
                    minimum_successes INTEGER NOT NULL,
                    auto_select_delegates INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
INSERT INTO "workspaces" VALUES('43996cb1-f0e4-45a5-8a47-8a42d040bc7b','Legacy workspace','d','ctx','["demo-a", "demo-b"]','{"demo-a": "skeptic"}','demo-critic','[]','demo-a','[]',2,0,'2026-11-13T14:14:16.584802+00:00','2026-11-13T14:14:16.584802+00:00');
CREATE INDEX idx_deliberation_runs_workspace_created
                ON deliberation_runs(workspace_id, created_at DESC)
                ;
COMMIT;
