# Install, first run and troubleshooting

Conclave is a single-user service that runs on your own machine and serves a web console on loopback. It needs Python 3.11 or newer. Node.js is needed only to run the console's rendering tests.

## 1. Install

**Windows (PowerShell)**

```powershell
git clone https://github.com/khantroll/Conclave.git
cd Conclave
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

**Linux or macOS**

```bash
git clone https://github.com/khantroll/Conclave.git
cd Conclave
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Add `".[dev]"` instead of `.` if you also want the test tools.

## 2. Start it

From the directory where you want `conclave.json`, `.env` and `conclave.db` to live:

```bash
uvicorn conclave.api:app
```

Open `http://127.0.0.1:8000/`. With no configuration, only four built-in `demo-*` providers exist. They return canned text, so they prove the pipeline runs and say nothing about answer quality. The console says "demo only" until you add real providers.

Do not bind it to another address. Conclave has no login; by default it answers only `127.0.0.1`, `localhost` and `[::1]` (see `docs/CONFIGURATION.md`, "Local access").

## 3. Add providers

Put the provider list in `conclave.json` next to where you start the server, and the keys in a `.env` file in the same directory. Keys are read from the environment variable named by `api_key_env`; they are never stored in the database.

`conclave.json`:

```json
{
  "providers": [
    {
      "name": "groq",
      "base_url": "https://api.groq.com/openai/v1",
      "model": "openai/gpt-oss-120b",
      "api_key_env": "GROQ_API_KEY",
      "family": "openai",
      "max_output_tokens": 1500,
      "input_cost_per_million": 0.0,
      "output_cost_per_million": 0.0
    },
    {
      "name": "qwen-flash",
      "base_url": "https://openrouter.ai/api/v1",
      "model": "qwen/qwen3.7-flash",
      "api_key_env": "OPENROUTER_API_KEY",
      "family": "qwen",
      "max_output_tokens": 4000,
      "input_cost_per_million": 0.03,
      "output_cost_per_million": 0.13,
      "reported_cost_field": "usage.cost"
    },
    {
      "name": "gemini",
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "model": "gemini-3.6-flash",
      "api_key_env": "GEMINI_API_KEY",
      "family": "google"
    }
  ]
}
```

`.env`:

```text
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
GEMINI_API_KEY=...
```

Rules worth knowing:

- Anything speaking the OpenAI chat-completions protocol works: direct vendor APIs, OpenRouter, LiteLLM Proxy, LM Studio and other local endpoints. A local endpoint may omit `api_key_env`.
- An interactive app subscription (a chat product, or a CLI login) is not an API key and does not give Conclave access. Use an API key from the provider's developer console.
- Prices are yours to fill in from the provider's current price list. A missing price is shown as unknown, never as zero.
- To use the cost ceiling (below), a provider also needs both prices and `max_output_tokens`.
- A provider that picks a model per call (for example `openrouter/free`) needs `"router_alias": true` so it is identified by the model it reports.
- Restart Conclave after editing `conclave.json` or `.env`.

Every field is documented in `docs/CONFIGURATION.md`.

## 4. Check the providers

The console's **Dashboard** lists each provider with its model, whether a credential is set (set is not the same as valid), capabilities, prices, limits, and the last success and last failure the call ledger recorded. Quota and context-window figures show "unknown" because no provider reports them to Conclave. Press **Test all configured** in the Providers panel to send each one a tiny request.

## 5. Create a workspace and run the first panel

1. In the console, open **Create workspace**. Give it a name, list the delegates (for example `groq, qwen-flash, gemini`), choose the Arbiter (one provider) and, if you want, fallbacks. Choose whether to use a Critic: there is no default, so you must choose "none" or name a provider. Set **Minimum successes** to the number of independent sources you require (2 or 3 is typical).
2. Select the workspace, type a question, and press **Deliberate**.
3. Read the result from the top: each delegate's position, then the Arbiter's four sections (common ground, disagreements, uncertainty, synthesis), then the delegates' raw answers. Disagreement is shown, not smoothed over. Agreement among models is not evidence that they are right.
4. **Call ledger** shows every provider request of the run with its tokens and estimated cost. **Download run JSON** exports the run (questions, prompts and answers are in it; keys are not).

Optional **Run options** on the question panel: a cost ceiling in USD, a shared timeout for Critic and Arbiter fallbacks, reserves, and background mode (shows progress and lets you cancel). They are all off by default and explained in `docs/CONFIGURATION.md`, "Optional run controls".

## 6. Back up and recover

- Your data is `conclave.db` and the `run_logs/` directory; your settings are `conclave.json` and `.env`. Copy all four before upgrading Conclave.
- On start, an existing database that needs upgrading is copied to `conclave.db.bak-<schema>-<timestamp>`, the copy is verified, and only then is it upgraded. To go back, stop Conclave and put the backup in place of `conclave.db`.
- A run interrupted by a crash or restart is marked `interrupted` the next time Conclave starts. Every answer received before the interruption is kept, and the retry buttons re-run only the missing stage.

## 7. Troubleshooting

| What you see | Likely cause and fix |
|---|---|
| Console says "demo only" | No `conclave.json` was found in the directory you started from, or its providers failed to load. Start Conclave from the directory that holds it, or set `CONCLAVE_CONFIG_PATH`. |
| Provider `credentials` shows `missing` | The environment variable named by `api_key_env` is not set. Check `.env` is in the directory you started from, then restart. |
| Test returns `auth` (401 or 403) | The key is wrong, expired, or belongs to a different service. |
| Test or run returns `rate_limit` or `quota` | Free tiers are small (Gemini's free tier allows about 20 requests a day per model; Mistral rate-limits readily). Wait, or use another provider. Conclave retries rate limits a bounded number of times and then reports the failure. |
| `timeout` | The model was slower than the run's timeout (60 s for delegates by default). Reasoning models can take longer; raise the timeout in the request. |
| `malformed` with "finish_reason length" | A reasoning model spent its whole output budget thinking. Raise `max_output_tokens` for that provider. |
| 422 "quorum unreachable" before any call | Fewer independent sources than the quorum asks for (two delegates on the same model count as one). Add a different model or lower the quorum. |
| 422 "cost ceiling needs a known cost" | A participant has no price, no `max_output_tokens`, or no retry limit configured. Fill them in, or run without a ceiling. |
| 403 "Host not allowed" | You are reaching Conclave by an address other than loopback. Use `http://127.0.0.1:8000/`, or set `CONCLAVE_ALLOWED_HOSTS` if you understand the exposure. |
| A run says `interrupted` | The process stopped, or you cancelled it. Open it from History and retry the missing stage. |

## 8. Run the tests

```bash
pip install -e ".[dev]"
pytest -q
node --test web/render.test.mjs
ruff check .
```

Tests use fake providers and block network access. They never read your `conclave.json`, `.env` or database.
