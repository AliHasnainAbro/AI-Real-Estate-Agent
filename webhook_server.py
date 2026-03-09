# ============================================================
# webhook_server.py
# ─────────────────────────────────────────────────────────
# FastAPI server — the bridge between Make.com and Python.
#
# Make.com cannot run Python directly.
# Make.com sends HTTP requests → this server runs Python code.
#
# HOW TO START:
#   uvicorn webhook_server:app --host 0.0.0.0 --port 8000
#
# EXPOSE TO INTERNET (so Make.com can reach it):
#   ngrok http 8000
#   → copy the https://xxxxx.ngrok-free.app URL into Make.com
#
# ENDPOINTS:
#   POST /run-matching    ← Scenario 1: trigger matching engine
#   GET  /call-queue      ← Scenario 2: get pending calls
#   POST /trigger-call    ← Scenario 2: make one call
#   GET  /call-logs       ← Scenario 3: daily summary data
#   POST /new-deal        ← optional: re-match on new deal
#   POST /new-client      ← optional: re-match on new client
#   GET  /health          ← Make.com monitoring ping
# ============================================================

import json
import os
import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="AI Real Estate Agent",
    description="Make.com webhook bridge for Saudi real estate AI agent",
    version="1.0.0",
)

# Secret header — paste this same value into Make.com HTTP module
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-this-secret")


# ── SECURITY ─────────────────────────────────────────────────
def require_auth(request: Request):
    """
    Verify the x-webhook-secret header matches .env value.
    Rejects all unauthorized requests with 401.
    """
    incoming = request.headers.get("x-webhook-secret", "")
    if incoming != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized — wrong or missing x-webhook-secret header"
        )


def ok(data: dict) -> JSONResponse:
    """Helper: return 200 JSON response."""
    return JSONResponse({**data, "timestamp": datetime.datetime.now().isoformat()})


def err(message: str, code: int = 500) -> JSONResponse:
    """Helper: return error JSON response."""
    return JSONResponse(
        {"status": "error", "message": message,
         "timestamp": datetime.datetime.now().isoformat()},
        status_code=code
    )


# ════════════════════════════════════════════════════════════
# ROUTE 1: POST /run-matching
# ────────────────────────────────────────────────────────────
# Make.com Scenario 1 sends a POST here when:
#   - New row appears in Inventory sheet
#   - New row appears in Clients sheet
#   - Scheduled run (every X minutes)
#
# Make.com setup:
#   Module: HTTP → Make a Request
#   URL:    https://YOUR-URL.ngrok-free.app/run-matching
#   Method: POST
#   Headers:
#     x-webhook-secret: [your secret]
#     Content-Type: application/json
#   Body: {"triggered_by": "google_sheets", "timestamp": "{{now}}"}
# ════════════════════════════════════════════════════════════
@app.post("/run-matching")
async def run_matching(request: Request):
    """Trigger the matching engine. Called by Make.com Scenario 1."""
    require_auth(request)

    try:
        body = await request.json()
    except Exception:
        body = {}

    print(f"\n📥 /run-matching triggered by Make.com")
    print(f"   Source: {body.get('triggered_by', 'unknown')}")

    try:
        from matching_engine import (
            connect_to_sheets, load_sheets,
            normalize, run_matching_engine, export_matches
        )

        gc                     = connect_to_sheets()
        inventory, clients, wb = load_sheets(gc)
        inventory              = normalize(inventory)
        clients                = normalize(clients)
        matches_df             = run_matching_engine(inventory, clients)
        n_calls                = export_matches(matches_df, wb)

        high = int((matches_df["tier"] == "HIGH").sum()) if not matches_df.empty else 0
        med  = int((matches_df["tier"] == "MEDIUM").sum()) if not matches_df.empty else 0

        result = {
            "status":           "success",
            "matches_found":    len(matches_df),
            "high_matches":     high,
            "medium_matches":   med,
            "calls_queued":     n_calls,
            "call_queue_ready": n_calls > 0,
        }

        print(f"✅ Matching done: {len(matches_df)} matches | "
              f"{n_calls} calls queued")
        return ok(result)

    except Exception as e:
        print(f"❌ Matching error: {e}")
        return err(str(e))


# ════════════════════════════════════════════════════════════
# ROUTE 2: GET /call-queue
# ────────────────────────────────────────────────────────────
# Make.com Scenario 2 reads this FIRST to get the list of
# pending calls, then iterates each one to POST /trigger-call.
#
# Make.com setup:
#   Module: HTTP → Make a Request
#   URL:    https://YOUR-URL.ngrok-free.app/call-queue
#   Method: GET
#   Headers: x-webhook-secret: [your secret]
#
# Make.com then parses the "calls" array and passes each item
# to an Iterator module → feeds into /trigger-call.
# ════════════════════════════════════════════════════════════
@app.get("/call-queue")
async def get_call_queue(request: Request):
    """Return pending calls list. Called by Make.com Scenario 2."""
    require_auth(request)

    try:
        with open("data/call_queue.json", encoding="utf-8") as f:
            queue = json.load(f)

        pending = [c for c in queue if c.get("status") == "pending"]

        # Sort: HIGH first, then owner→broker→client order
        type_order = {"owner": 0, "broker": 1, "client": 2}
        pending.sort(key=lambda c: (
            0 if c.get("tier") == "HIGH" else 1,
            type_order.get(c.get("call_type", "client"), 2)
        ))

        return ok({
            "status":        "success",
            "total_in_queue": len(queue),
            "pending_calls": len(pending),
            "calls":         pending,
        })

    except FileNotFoundError:
        return ok({
            "status":        "success",
            "pending_calls": 0,
            "calls":         [],
            "message":       "No call queue yet — run matching first",
        })
    except Exception as e:
        return err(str(e))


# ════════════════════════════════════════════════════════════
# ROUTE 3: POST /trigger-call
# ────────────────────────────────────────────────────────────
# Make.com Scenario 2 sends ONE call target at a time here.
# This runs the complete call lifecycle for that contact.
#
# Make.com setup (inside Iterator loop):
#   Module: HTTP → Make a Request
#   URL:    https://YOUR-URL.ngrok-free.app/trigger-call
#   Method: POST
#   Headers:
#     x-webhook-secret: [your secret]
#     Content-Type: application/json
#   Body (JSON — map from Iterator fields):
#     {
#       "phone":       "{{iterator.phone}}",
#       "call_type":   "{{iterator.call_type}}",
#       "deal_id":     "{{iterator.deal_id}}",
#       "client_id":   "{{iterator.client_id}}",
#       "property":    "{{iterator.property}}",
#       "location":    "{{iterator.location}}",
#       "price":       {{iterator.price}},
#       "units":       {{iterator.units}},
#       "ticket_size": {{iterator.ticket_size}},
#       "score":       {{iterator.score}},
#       "tier":        "{{iterator.tier}}",
#       "client_name": "{{iterator.client_name}}"
#     }
#
# IMPORTANT: In Make.com Iterator settings → Sequential = ON
# (So calls go one at a time, not simultaneously)
# ════════════════════════════════════════════════════════════
@app.post("/trigger-call")
async def trigger_call(request: Request):
    """Make one outbound call. Called by Make.com Scenario 2 iterator."""
    require_auth(request)

    try:
        call_target = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # Validate required fields
    for field in ["phone", "call_type", "deal_id"]:
        if not call_target.get(field):
            raise HTTPException(400, f"Missing required field: {field}")

    valid_types = {"owner", "broker", "client"}
    if call_target["call_type"] not in valid_types:
        raise HTTPException(400,
            f"call_type must be one of: {valid_types}")

    print(f"\n📥 /trigger-call: "
          f"[{call_target['call_type'].upper()}] "
          f"{call_target['phone']}")

    try:
        from call_orchestrator import handle_call
        result = await handle_call(call_target)

        return ok({
            "status":    "success",
            "outcome":   result.get("outcome"),
            "turns":     result.get("turns", 0),
            "phone":     call_target["phone"],
            "call_type": call_target["call_type"],
            "deal_id":   call_target.get("deal_id"),
        })

    except Exception as e:
        print(f"❌ Call failed: {e}")
        return err(str(e))


# ════════════════════════════════════════════════════════════
# ROUTE 4: GET /call-logs
# ────────────────────────────────────────────────────────────
# Make.com Scenario 3 reads this to build a daily summary email.
#
# Make.com setup:
#   Module: HTTP → Make a Request
#   URL:    https://YOUR-URL.ngrok-free.app/call-logs?limit=100
#   Method: GET
#   Headers: x-webhook-secret: [your secret]
#
# Then: Email module → send summary to yourself
# ════════════════════════════════════════════════════════════
@app.get("/call-logs")
async def get_call_logs(request: Request, limit: int = 50):
    """Return recent call logs for daily reporting. Scenario 3."""
    require_auth(request)

    try:
        logs = []
        with open("logs/call_logs.jsonl", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        record = json.loads(line)
                        record.pop("transcript", None)  # Too large for summary
                        logs.append(record)
                    except json.JSONDecodeError:
                        continue

        logs = list(reversed(logs))[:limit]

        completed = sum(1 for l in logs if l.get("outcome") == "completed")
        failed    = sum(1 for l in logs if l.get("outcome") in
                        ("failed", "error"))

        return ok({
            "status":    "success",
            "total":     len(logs),
            "completed": completed,
            "failed":    failed,
            "success_rate": (round(completed / len(logs) * 100)
                             if logs else 0),
            "logs":      logs,
        })

    except FileNotFoundError:
        return ok({
            "status": "success", "total": 0,
            "completed": 0, "failed": 0,
            "success_rate": 0, "logs": [],
        })
    except Exception as e:
        return err(str(e))


# ════════════════════════════════════════════════════════════
# ROUTE 5: GET /health
# ────────────────────────────────────────════════════════════
# Make.com can ping this every 5 minutes to verify server is up.
# If it returns non-200, Make.com sends you an alert email.
#
# Make.com setup:
#   Scenario: Schedule → every 5 min → HTTP GET /health
#   If status != 200 → Gmail → send alert
# ════════════════════════════════════════════════════════════
@app.get("/health")
async def health_check():
    """Server liveness check for Make.com monitoring."""
    # Check if key files exist
    queue_exists = os.path.exists("data/call_queue.json")
    logs_exist   = os.path.exists("logs/call_logs.jsonl")

    return JSONResponse({
        "status":          "online",
        "service":         "AI Real Estate Agent",
        "timestamp":       datetime.datetime.now().isoformat(),
        "call_queue_ready": queue_exists,
        "logs_ready":      logs_exist,
    })


# ════════════════════════════════════════════════════════════
# ROUTE 6: POST /new-deal
# ────────────────────────────────────────────────────────────
# Make.com: Google Sheets → "Watch Rows" on Inventory tab
#           → POST /new-deal whenever new deal row added
# This re-runs matching so new deals get matched immediately.
# ════════════════════════════════════════════════════════════
@app.post("/new-deal")
async def new_deal(request: Request):
    """Re-trigger matching when a new deal is added to the sheet."""
    require_auth(request)

    try:
        data = await request.json()
        print(f"\n📥 New deal from Make.com: "
              f"{data.get('property_name', '?')} "
              f"in {data.get('location', '?')}")
    except Exception:
        pass

    # Forward to matching engine
    return await run_matching(request)


# ════════════════════════════════════════════════════════════
# ROUTE 7: POST /new-client
# ────────────────────────────────────────────────────────────
# Make.com: Google Sheets → "Watch Rows" on Clients tab
#           → POST /new-client whenever new client row added
# ════════════════════════════════════════════════════════════
@app.post("/new-client")
async def new_client(request: Request):
    """Re-trigger matching when a new client request is added."""
    require_auth(request)

    try:
        data = await request.json()
        print(f"\n📥 New client from Make.com: "
              f"{data.get('client_name', '?')}")
    except Exception:
        pass

    return await run_matching(request)