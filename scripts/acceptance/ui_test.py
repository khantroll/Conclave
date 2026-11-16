"""Drive the real console in headless Edge through the DevTools protocol."""

import asyncio
import json
import subprocess
import tempfile
import time
import urllib.request

import httpx
import websockets

import os

EDGE = os.environ.get("BROWSER", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BASE = "http://127.0.0.1:8765"

c = httpx.Client(base_url=BASE, timeout=60)
wid = c.post(
    "/api/workspaces",
    json={
        "name": "UI test workspace",
        "delegates": ["groq", "qwen-flash", "deepseek-v3"],
        "arbiter": "qwen-flash",
        "critic": None,
        "minimum_successes": 2,
        "single_source_mode": "return_answer",
    },
).json()["id"]

prof = tempfile.mkdtemp()
proc = subprocess.Popen(
    [EDGE, "--headless=new", "--disable-gpu", "--remote-debugging-port=9333",
     f"--user-data-dir={prof}", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(4)
targets = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
ws_url = [t for t in targets if t["type"] == "page"][0]["webSocketDebuggerUrl"]
errors = []


async def main():
    async with websockets.connect(ws_url, max_size=50_000_000) as ws:
        n = 0
        pending = {}

        async def reader():
            async for raw in ws:
                m = json.loads(raw)
                if "id" in m:
                    pending[m["id"]].set_result(m)
                elif m.get("method") == "Runtime.exceptionThrown":
                    errors.append(m["params"]["exceptionDetails"].get("text", "") + str(m["params"]["exceptionDetails"].get("exception", {}).get("description", "")))
                elif m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] == "error":
                    errors.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"]))

        asyncio.create_task(reader())

        async def call(method, **params):
            nonlocal n
            n += 1
            fut = asyncio.get_event_loop().create_future()
            pending[n] = fut
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            return (await fut).get("result", {})

        async def js(expr):
            r = await call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
            return r.get("result", {}).get("value")

        await call("Runtime.enable")
        await call("Page.enable")
        await call("Page.navigate", url=BASE + "/")
        await asyncio.sleep(4)
        out = {}
        out["dashboard_text"] = await js("document.getElementById('dashboardSummary').textContent")
        out["provider_rows"] = await js("document.querySelectorAll('#providerStatus tbody tr').length")
        # choose the workspace, type a question, run in the background
        await js(f"(()=>{{const s=document.getElementById('workspaceSelect');s.value='{wid}';s.dispatchEvent(new Event('change'));}})()")
        await asyncio.sleep(1)
        await js("document.getElementById('question').value='Name one advantage and one risk of microservices, in two sentences.'")
        await js("document.getElementById('optBackground').checked=true; document.getElementById('optCostCeiling').value='0.05'")
        await js("document.getElementById('runButton').click()")
        saw_cancel = False
        for _ in range(120):
            await asyncio.sleep(1)
            vis = await js("!document.getElementById('cancelRun').classList.contains('hidden')")
            saw_cancel = saw_cancel or bool(vis)
            done = await js("!document.getElementById('answerSection').classList.contains('hidden') && !document.getElementById('runButton').disabled")
            if done:
                break
        out["cancel_button_seen_during_run"] = saw_cancel
        out["status"] = await js("document.getElementById('status').textContent")
        out["positions_rows"] = await js("document.querySelectorAll('#positionsTable tr').length")
        out["arbiter_sections"] = await js("document.getElementById('arbiterStructured').textContent.slice(0,300)")
        out["delegate_cards"] = await js("document.querySelectorAll('#delegateCards > *').length")
        out["cost_summary"] = await js("document.getElementById('costSummary').textContent")
        await js("document.getElementById('showLedger').click()")
        await asyncio.sleep(1.5)
        out["ledger_rows"] = await js("document.querySelectorAll('#ledgerBody tbody tr').length")
        out["history_items"] = await js("document.querySelectorAll('#history .history-item').length")

        # second run: start in the background and press Cancel
        await js("document.getElementById('optCostCeiling').value=''")
        await js("document.getElementById('question').value='Explain, in detail, five trade-offs of event sourcing.'")
        await js("document.getElementById('runButton').click()")
        await asyncio.sleep(2)
        await js("document.getElementById('cancelRun').click()")
        await asyncio.sleep(4)
        out["after_cancel_status"] = await js("document.getElementById('status').textContent")
        out["run_button_enabled_again"] = await js("!document.getElementById('runButton').disabled")
        out["js_errors"] = errors
        print(json.dumps(out, indent=1, ensure_ascii=False))


try:
    asyncio.run(main())
finally:
    proc.terminate()
