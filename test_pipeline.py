# ============================================================
# test_pipeline.py
# ─────────────────────────────────────────────────────────
# Run ALL tests before making live calls.
# Tests every component independently with sample data.
# ALL 5 tests must pass before you go live.
#
# HOW TO RUN:
#   python test_pipeline.py
# ============================================================

import asyncio
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()


def bar(title: str):
    print(f"\n{'─'*55}")
    print(f"  🧪 TEST: {title}")
    print(f"{'─'*55}")


# ── TEST 1: MATCHING ENGINE ───────────────────────────────────
def test_matching() -> bool:
    bar("Matching Engine (no Google Sheets — uses sample data)")

    try:
        import pandas as pd
        from matching_engine import normalize, run_matching_engine

        inventory = pd.DataFrame([
            {
                "deal_id": "D001",
                "property_name": "برج الأعمال",
                "location": "العليا، الرياض",
                "price": 1_850_000,
                "units": 4,
                "ticket_size": 450_000,
                "owner_phone": "+966501111111",
                "broker_phone": "+966502222222",
            },
            {
                "deal_id": "D002",
                "property_name": "مجمع الشموس",
                "location": "النخيل، الرياض",
                "price": 3_200_000,
                "units": 8,
                "ticket_size": 800_000,
                "owner_phone": "+966503333333",
                "broker_phone": "+966504444444",
            },
            {
                "deal_id": "D003",
                "property_name": "واجهة الخليج",
                "location": "جدة",
                "price": 9_000_000,   # Too expensive — should not match
                "units": 20,
                "ticket_size": 2_000_000,
                "owner_phone": "+966505555555",
                "broker_phone": "",
            },
        ])

        clients = pd.DataFrame([
            {
                "client_id": "C001",
                "client_name": "محمد العمري",
                "budget_max": 2_000_000,
                "budget_min": 1_500_000,
                "desired_units": 4,
                "ticket_size_max": 500_000,
                "phone": "+966509876543",
                "request_date": "2026-02-01",
            },
            {
                "client_id": "C002",
                "client_name": "سلطان الغامدي",
                "budget_max": 3_500_000,
                "budget_min": 2_800_000,
                "desired_units": 8,
                "ticket_size_max": 850_000,
                "phone": "+966503456789",
                "request_date": "2026-02-15",
            },
        ])

        inventory = normalize(inventory)
        clients   = normalize(clients)
        matches   = run_matching_engine(inventory, clients)

        if matches.empty:
            print("❌ FAIL — No matches found with sample data")
            return False

        # D003 should NOT appear (too expensive)
        if "D003" in matches["deal_id"].values:
            print("❌ FAIL — D003 should not match (price too high)")
            return False

        print(f"✅ PASS — {len(matches)} match(es) found")
        print(matches[["deal_id", "client_id", "score",
                        "tier", "property"]].to_string(index=False))

        # Save sample queue for queue test
        os.makedirs("data", exist_ok=True)
        # Quick call queue for queue test
        queue_sample = [{
            "call_type": "client",
            "phone": "+966509876543",
            "deal_id": "D001",
            "client_id": "C001",
            "property": "برج الأعمال",
            "location": "العليا، الرياض",
            "price": 1850000,
            "units": 4,
            "ticket_size": 450000,
            "score": 85,
            "tier": "HIGH",
            "client_name": "محمد العمري",
            "status": "pending",
        }]
        with open("data/call_queue.json", "w", encoding="utf-8") as f:
            json.dump(queue_sample, f, ensure_ascii=False)

        return True

    except Exception as e:
        print(f"❌ FAIL — Exception: {e}")
        import traceback; traceback.print_exc()
        return False


# ── TEST 2: SYSTEM PROMPTS ────────────────────────────────────
def test_prompts() -> bool:
    bar("System Prompts (all 3 scenarios)")

    try:
        from system_prompts import get_prompt_for_call_type

        sample_deal = {
            "property":    "برج الأعمال",
            "location":    "العليا، الرياض",
            "price":       1_850_000,
            "units":       4,
            "ticket_size": 450_000,
            "deal_id":     "D001",
            "client_name": "أحمد",
        }

        all_ok = True
        for call_type in ["owner", "broker", "client"]:
            try:
                prompt = get_prompt_for_call_type(call_type, sample_deal)
                words  = len(prompt.split())
                # Verify key dialect words are present
                has_dialect = any(w in prompt for w in
                                  ["وش", "زين", "أبغى", "نسوي", "بس"])
                # Verify Fusha ban is stated
                has_ban = "بالتأكيد" in prompt or "فصحى" in prompt

                status = "✅" if (words > 50 and has_dialect) else "⚠️"
                print(f"  {status} {call_type:8} — {words} words | "
                      f"dialect terms: {has_dialect} | "
                      f"fusha ban: {has_ban}")

                if words < 50:
                    all_ok = False

            except Exception as e:
                print(f"  ❌ {call_type} failed: {e}")
                all_ok = False

        if all_ok:
            print("✅ PASS — All 3 prompts loaded correctly")
        return all_ok

    except Exception as e:
        print(f"❌ FAIL — {e}")
        return False


# ── TEST 3: CALL QUEUE FILE ───────────────────────────────────
def test_call_queue() -> bool:
    bar("Call Queue File (data/call_queue.json)")

    try:
        with open("data/call_queue.json", encoding="utf-8") as f:
            queue = json.load(f)

        if not isinstance(queue, list):
            print("❌ FAIL — call_queue.json is not a list")
            return False

        pending = [c for c in queue if c.get("status") == "pending"]

        print(f"✅ PASS — {len(queue)} total | {len(pending)} pending")

        # Show first 3
        for item in queue[:3]:
            print(f"   [{item.get('call_type','?').upper()}] "
                  f"{item.get('phone','?')} | "
                  f"{item.get('property','?')} | "
                  f"Score: {item.get('score','?')}")
        return True

    except FileNotFoundError:
        print("⚠️  call_queue.json not found — run Test 1 first")
        return False
    except Exception as e:
        print(f"❌ FAIL — {e}")
        return False


# ── TEST 4: LLM BRAIN (Groq) ─────────────────────────────────
async def test_llm() -> bool:
    bar("LLM Brain — Groq API + Saudi Dialect")

    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key or groq_key == "gsk_your_groq_key_here":
        print("⚠️  SKIP — GROQ_API_KEY not set in .env")
        print("   Get your free key at: https://console.groq.com")
        return True  # Non-blocking skip

    try:
        from llm_brain import get_agent_response
        from system_prompts import get_client_prompt
        from voice_pipeline import check_dialect_drift

        deal = {
            "property":    "برج الأعمال",
            "location":    "العليا",
            "price":       1_850_000,
            "units":       4,
            "ticket_size": 450_000,
            "client_name": "محمد",
        }

        system_prompt = get_client_prompt(deal)

        history = [
            {"role": "assistant",
             "content": "السلام عليكم محمد، معك فهد من الشركة. "
                        "عندي خبر حلو — لقينا لك عقار يطابق طلبك."},
            {"role": "user", "content": "وش هو العقار؟"},
        ]

        reply = await get_agent_response(history, system_prompt)

        if not reply:
            print("❌ FAIL — Empty reply from LLM")
            return False

        print(f"   Agent reply: {reply}")

        drift = check_dialect_drift(reply)
        if drift:
            print("⚠️  WARNING — Fusha markers detected in reply")
            print("   This may need prompt tuning")
        else:
            print("✅ No Fusha drift detected")

        print("✅ PASS — Groq API responding")
        return True

    except Exception as e:
        print(f"❌ FAIL — {e}")
        return False


# ── TEST 5: TTS VOICE ─────────────────────────────────────────
async def test_tts() -> bool:
    bar("Text-to-Speech Voice Generation")

    try:
        from voice_pipeline import synthesize_speech

        test_text = "السلام عليكم، معك فهد من الشركة. كيف حالك؟"
        print(f"   Synthesizing: '{test_text}'")

        audio = await synthesize_speech(test_text)

        if not audio or len(audio) < 100:
            print("❌ FAIL — No audio returned (check ElevenLabs key)")
            return False

        os.makedirs("data", exist_ok=True)
        out_path = "data/test_voice_sample.mp3"
        with open(out_path, "wb") as f:
            f.write(audio)

        print(f"✅ PASS — {len(audio):,} bytes generated")
        print(f"   🎧 Listen: {out_path}")
        return True

    except Exception as e:
        print(f"❌ FAIL — {e}")
        return False


# ── TEST 6: WEBHOOK SERVER ────────────────────────────────────
def test_webhook_imports() -> bool:
    bar("Webhook Server (import check)")

    try:
        import fastapi
        import uvicorn
        from webhook_server import app

        routes = [r.path for r in app.routes]
        expected = ["/run-matching", "/call-queue",
                    "/trigger-call", "/call-logs", "/health"]
        missing = [r for r in expected if r not in routes]

        if missing:
            print(f"❌ FAIL — Missing routes: {missing}")
            return False

        print(f"✅ PASS — FastAPI app imports OK")
        print(f"   Routes: {[r for r in routes if r != '/openapi.json' and r != '/docs' and r != '/redoc']}")
        return True

    except ImportError as e:
        print(f"❌ FAIL — Import error: {e}")
        print("   Run: pip install fastapi uvicorn")
        return False
    except Exception as e:
        print(f"❌ FAIL — {e}")
        return False


# ── MAIN ──────────────────────────────────────────────────────
async def run_all():
    print("\n" + "="*55)
    print("  AI REAL ESTATE AGENT — FULL PIPELINE TEST")
    print("="*55)

    results = {}

    results["1. Matching Engine"]   = test_matching()
    results["2. System Prompts"]    = test_prompts()
    results["3. Call Queue File"]   = test_call_queue()
    results["4. LLM Brain (Groq)"]  = await test_llm()
    results["5. TTS Voice"]         = await test_tts()
    results["6. Webhook Server"]    = test_webhook_imports()

    # ── Summary ───────────────────────────────────────────────
    print(f"\n{'='*55}")
    print("  RESULTS")
    print(f"{'='*55}")
    all_passed = True
    for name, passed in results.items():
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {name}")
        if not passed:
            all_passed = False

    print(f"{'='*55}")

    if all_passed:
        print("🎉 ALL TESTS PASSED\n")
        print("   Next steps:")
        print("   1. uvicorn webhook_server:app --host 0.0.0.0 --port 8000")
        print("   2. ngrok http 8000")
        print("   3. Build Make.com scenarios (see SETUP_GUIDE.md)")
        print("   4. python call_orchestrator.py  ← for manual test call")
    else:
        print("⚠️  SOME TESTS FAILED\n")
        print("   Fix the failed tests before making live calls.")
        print("   Check your .env file and API keys.")

    print(f"{'='*55}\n")
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(run_all())
    sys.exit(0 if success else 1)