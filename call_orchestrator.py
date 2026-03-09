# ============================================================
# call_orchestrator.py
# ─────────────────────────────────────────────────────────
# WHAT IT DOES:
#   Reads call_queue.json → triggers outbound SIP calls via
#   partner server → manages full listen→transcribe→think→speak
#   loop → logs every call with full Arabic transcript.
#
# HOW TO RUN:
#   python call_orchestrator.py
#
# OR triggered via Make.com → webhook_server.py → handle_call()
# ============================================================

import asyncio
import aiohttp
import websockets
import json
import os
import datetime
from dotenv import load_dotenv

from system_prompts import get_prompt_for_call_type
from voice_pipeline import transcribe_audio, synthesize_speech
from llm_brain import get_agent_response, is_call_ending, get_opening_line

load_dotenv()

PARTNER_API_BASE = os.getenv("PARTNER_API_BASE", "")
PARTNER_API_KEY  = os.getenv("PARTNER_API_KEY",  "")
SIP_CALLER_ID    = os.getenv("SIP_CALLER_ID",    "")
CALL_QUEUE_FILE  = "data/call_queue.json"
LOG_FILE         = "logs/call_logs.jsonl"
MAX_TURNS        = 15   # Safety cap — end call after this many exchanges

os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)


# ── 1: INITIATE OUTBOUND CALL ────────────────────────────────
async def initiate_call(phone: str, call_type: str) -> dict | None:
    """
    POST to partner's Vapi-like server → start an outbound SIP call.

    Expected response from partner:
    {
        "call_id": "abc-123",
        "ws_audio_url": "wss://partner-server.com/audio/abc-123"
    }

    Returns the response dict, or None if the call failed to start.
    """
    if not PARTNER_API_BASE or not PARTNER_API_KEY:
        print("❌ PARTNER_API_BASE or PARTNER_API_KEY not set in .env")
        return None

    payload = {
        "to":       phone,
        "from":     SIP_CALLER_ID,
        "metadata": {
            "call_type": call_type,
            "language":  "ar-SA",
        },
    }

    headers = {
        "Authorization": f"Bearer {PARTNER_API_KEY}",
        "Content-Type":  "application/json",
    }

    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                f"{PARTNER_API_BASE}/calls/outbound",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    print(f"📞 Call started | ID: {data.get('call_id', '?')}")
                    return data
                else:
                    err = await resp.text()
                    print(f"❌ Partner API {resp.status}: {err[:150]}")
                    return None

    except aiohttp.ClientError as e:
        print(f"❌ Cannot reach partner API: {e}")
        return None


# ── 2: FULL CALL LIFECYCLE ────────────────────────────────────
async def handle_call(call_target: dict) -> dict:
    """
    Full call lifecycle for one contact:
      1. Get system prompt for this call type
      2. Trigger outbound call via partner API
      3. Open WebSocket audio stream
      4. Send opening line immediately
      5. Listen → Transcribe → LLM → Speak loop
      6. Detect call ending or max turns
      7. Log everything and return result

    Args:
        call_target: one item from call_queue.json
            {phone, call_type, deal_id, client_id,
             property, location, price, units,
             ticket_size, score, tier, client_name}

    Returns: log record dict with outcome and transcript
    """
    phone     = call_target.get("phone", "")
    call_type = call_target.get("call_type", "client")

    print(f"\n{'='*55}")
    print(f"📞 [{call_type.upper()}] → {phone}")
    print(f"   Property : {call_target.get('property', '')}")
    print(f"   Location : {call_target.get('location', '')}")
    print(f"   Score    : {call_target.get('score', 0)}  "
          f"({call_target.get('tier', '')})")
    print(f"{'='*55}")

    # ── Get appropriate system prompt ─────────────────────────
    try:
        system_prompt = get_prompt_for_call_type(call_type, call_target)
    except ValueError as e:
        print(f"❌ Invalid call_type: {e}")
        return _log_call(call_target, [], "failed", str(e))

    # ── Initiate outbound call ────────────────────────────────
    session_info = await initiate_call(phone, call_type)
    if not session_info:
        return _log_call(call_target, [], "failed",
                         "Could not initiate call with partner API")

    # Partner must return a WebSocket URL for the audio stream
    ws_url  = (session_info.get("ws_audio_url") or
               session_info.get("websocket_url") or
               session_info.get("audio_ws"))
    call_id = session_info.get("call_id", "unknown")

    if not ws_url:
        print("❌ No WebSocket URL in partner response")
        print(f"   Full response: {session_info}")
        return _log_call(call_target, [], "failed",
                         "No WebSocket URL returned by partner")

    # ── Build opening line ────────────────────────────────────
    opening_text  = get_opening_line(call_type, call_target)
    opening_audio = await synthesize_speech(opening_text)

    conversation_history = [
        {"role": "assistant", "content": opening_text}
    ]

    outcome        = "completed"
    outcome_reason = ""
    turn_count     = 0

    # ── Open WebSocket and run conversation ───────────────────
    try:
        async with websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {PARTNER_API_KEY}"},
            ping_interval=20,
            ping_timeout=30,
            close_timeout=10,
        ) as ws:

            print(f"🔗 WebSocket open | Call ID: {call_id}")

            # Send opening line immediately
            await ws.send(opening_audio)
            print(f"🤖 Agent: {opening_text}")

            # ── Main listen/respond loop ──────────────────────
            async for audio_chunk in ws:

                # Only process binary audio frames
                if not isinstance(audio_chunk, bytes):
                    continue
                if len(audio_chunk) < 200:
                    continue  # Silence / keepalive packet

                # Transcribe caller's speech → text
                user_text = transcribe_audio(audio_chunk)
                if not user_text:
                    continue  # Nothing transcribed — wait for more

                print(f"👤 Caller: {user_text}")
                turn_count += 1

                # Check if caller wants to end
                if is_call_ending(user_text):
                    farewell = "زين، شكراً — يوم سعيد إن شاء الله!"
                    await ws.send(await synthesize_speech(farewell))
                    print(f"🤖 Agent: {farewell}")
                    outcome_reason = "Caller ended call naturally"
                    break

                # Add user turn to history
                conversation_history.append({
                    "role":    "user",
                    "content": user_text,
                })

                # Get LLM response
                agent_reply = await get_agent_response(
                    conversation_history, system_prompt
                )
                print(f"🤖 Agent: {agent_reply}")

                # Add agent turn to history
                conversation_history.append({
                    "role":    "assistant",
                    "content": agent_reply,
                })

                # Convert to audio and send
                reply_audio = await synthesize_speech(agent_reply)
                await ws.send(reply_audio)

                # Safety cap — don't let calls run forever
                if turn_count >= MAX_TURNS:
                    close_msg = ("زين، شكراً على وقتك — "
                                 "بنتواصل معك قريباً. مع السلامة!")
                    await ws.send(await synthesize_speech(close_msg))
                    outcome_reason = f"Reached max turns ({MAX_TURNS})"
                    print(f"⏹️  Max turns reached — ending call")
                    break

    except websockets.exceptions.ConnectionClosed as e:
        print(f"📵 WebSocket closed: {e}")
        outcome_reason = f"Connection closed: {e.code}"

    except websockets.exceptions.WebSocketException as e:
        print(f"❌ WebSocket error: {e}")
        outcome        = "error"
        outcome_reason = str(e)

    except Exception as e:
        print(f"❌ Unexpected call error: {e}")
        outcome        = "error"
        outcome_reason = str(e)

    return _log_call(call_target, conversation_history,
                     outcome, outcome_reason)


# ── LOGGING ───────────────────────────────────────────────────
def _log_call(call_target: dict,
              history: list,
              outcome: str,
              reason: str = "") -> dict:
    """Write call result to JSONL log file and return the record."""
    user_turns = [m for m in history if m["role"] == "user"]

    record = {
        "timestamp":  datetime.datetime.now().isoformat(),
        "phone":      call_target.get("phone"),
        "call_type":  call_target.get("call_type"),
        "deal_id":    call_target.get("deal_id"),
        "client_id":  call_target.get("client_id"),
        "property":   call_target.get("property"),
        "score":      call_target.get("score"),
        "tier":       call_target.get("tier"),
        "outcome":    outcome,
        "reason":     reason,
        "turns":      len(user_turns),
        "transcript": history,
    }

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️  Log write failed: {e}")

    icon = "✅" if outcome == "completed" else "❌"
    print(f"\n{icon} Call logged | "
          f"Outcome: {outcome} | "
          f"Turns: {record['turns']} | "
          f"Reason: {reason or 'N/A'}\n")
    return record


# ── STANDALONE RUNNER ─────────────────────────────────────────
async def main():
    """
    Load call_queue.json and make all calls sequentially.
    HIGH priority calls go first, then MEDIUM.
    """
    print("\n" + "="*55)
    print("  CALL ORCHESTRATOR — AI Real Estate Agent")
    print("="*55 + "\n")

    # Load call queue
    try:
        with open(CALL_QUEUE_FILE, encoding="utf-8") as f:
            call_queue = json.load(f)
    except FileNotFoundError:
        print(f"❌ {CALL_QUEUE_FILE} not found.")
        print("   Run: python matching_engine.py first")
        return

    # Filter to pending only
    pending = [c for c in call_queue if c.get("status") == "pending"]

    if not pending:
        print("✅ No pending calls in queue.")
        return

    # Sort: HIGH first, then MEDIUM; within each tier owner→broker→client
    type_order = {"owner": 0, "broker": 1, "client": 2}
    pending.sort(key=lambda c: (
        0 if c.get("tier") == "HIGH" else 1,
        type_order.get(c.get("call_type", "client"), 2)
    ))

    print(f"📋 {len(pending)} pending calls\n")

    results = []
    for i, call_target in enumerate(pending, 1):
        print(f"[{i}/{len(pending)}] Next: "
              f"{call_target['call_type'].upper()} → "
              f"{call_target['phone']}")

        result = await handle_call(call_target)
        results.append(result)

        # Pause between calls — avoid SIP flooding
        if i < len(pending):
            print("⏳ Pausing 8 seconds...")
            await asyncio.sleep(8)

    # ── Session summary ───────────────────────────────────────
    completed = sum(1 for r in results if r["outcome"] == "completed")
    failed    = len(results) - completed

    print(f"\n{'='*55}")
    print(f"📊 SESSION COMPLETE")
    print(f"   Total  : {len(results)}")
    print(f"   ✅ Done : {completed}")
    print(f"   ❌ Failed: {failed}")
    print(f"   Logs   : {LOG_FILE}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(main())