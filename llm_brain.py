# ============================================================
# llm_brain.py
# ─────────────────────────────────────────────────────────
# The AI conversation brain.
# Uses Groq API (free tier) with llama-3.3-70b-versatile.
# Enforces Saudi dialect on every response.
# Detects call endings and provides opening lines.
# ============================================================

import os
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"   # Best free model on Groq
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

AGENT_NAME   = os.getenv("AGENT_NAME",   "فهد")
COMPANY_NAME = os.getenv("COMPANY_NAME", "الشركة")


# ── LLM CALL ────────────────────────────────────────────────
async def get_agent_response(conversation_history: list,
                              system_prompt: str,
                              max_retries: int = 2) -> str:
    """
    Send conversation history to Groq LLM → get Saudi dialect reply.

    Flow:
      1. Call Groq API with system prompt + full history
      2. Check response for Fusha (dialect drift)
      3. If drift detected → ask LLM to self-correct (up to 2 retries)
      4. If still drifted → apply text substitution fixes
      5. Return final cleaned response

    Args:
        conversation_history: list of {"role": ..., "content": ...}
        system_prompt: the caller-type-specific system prompt
        max_retries: how many times to retry if dialect drifts

    Returns: Saudi dialect string response
    """
    from voice_pipeline import check_dialect_drift, fix_dialect_drift

    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set in .env")
        return "عذراً، في مشكلة تقنية."

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }

    messages = [
        {"role": "system", "content": system_prompt},
        *conversation_history,
    ]

    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "max_tokens":  180,    # Keep responses short for voice
        "temperature": 0.35,   # Low = consistent dialect, less drift
        "top_p":       0.85,
    }

    for attempt in range(max_retries + 1):
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    GROQ_URL, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=12)
                ) as resp:

                    if resp.status == 200:
                        data  = await resp.json()
                        reply = (data["choices"][0]["message"]["content"]
                                 .strip())

                        # ── Dialect check ──────────────────────
                        if check_dialect_drift(reply):
                            print(f"⚠️  Fusha drift (attempt {attempt+1}): "
                                  f"{reply[:60]}...")

                            if attempt < max_retries:
                                # Inject self-correction message
                                correction = (
                                    "تنبيه مهم: ردك الأخير فيه فصحى. "
                                    "أعد نفس الرد بالعامية السعودية النجدية "
                                    "فقط — بدون أي فصحى:\n"
                                    f"الرد الأصلي: {reply}"
                                )
                                payload["messages"] = [
                                    *payload["messages"],
                                    {"role": "assistant",
                                     "content": reply},
                                    {"role": "user",
                                     "content": correction},
                                ]
                                continue  # Retry

                            # Last resort: text substitution
                            reply = fix_dialect_drift(reply)
                            print("🔧 Applied dialect fix substitutions")

                        return reply

                    elif resp.status == 429:
                        # Rate limit — wait and retry
                        wait = 3 * (attempt + 1)
                        print(f"⏳ Groq rate limit — waiting {wait}s...")
                        await asyncio.sleep(wait)
                        continue

                    else:
                        err = await resp.text()
                        print(f"❌ Groq {resp.status}: {err[:100]}")
                        return "عذراً، ما قدرت أفهم — تعيد عليّ؟"

        except asyncio.TimeoutError:
            print(f"⏰ Groq timeout (attempt {attempt+1})")
            if attempt < max_retries:
                continue
            return "عذراً، في تأخير — تعيد السؤال؟"

        except Exception as e:
            print(f"❌ LLM error: {e}")
            return "عذراً، في مشكلة تقنية — نحاول مرة ثانية"

    return "عذراً، ما قدرت أكمل — بنتواصل معك لاحقاً"


# ── CALL END DETECTION ────────────────────────────────────────
# Phrases that signal the caller wants to end the conversation
END_PHRASES = [
    "مع السلامة", "باي", "إلى اللقاء",
    "يكفي", "كفاية", "خلاص",
    "ما أبغى", "مو مهتم", "مو مهتمة",
    "لا شكراً", "لا، شكراً",
    "مشغول", "مشغولة", "ما عندي وقت",
    "بعدين أتصل", "أنا أتصل عليك",
    "شكراً مع السلامة", "يسلمك",
]


def is_call_ending(text: str) -> bool:
    """
    Returns True if caller's text contains a call-ending phrase.
    Case-insensitive and handles partial matches.
    """
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in END_PHRASES)


# ── OPENING LINES ─────────────────────────────────────────────
def get_opening_line(call_type: str, deal: dict) -> str:
    """
    The first thing the agent says when the call connects.
    Must be: short, warm, in Saudi dialect, and give context immediately.
    """
    if call_type == "owner":
        return (
            f"السلام عليكم، معك {AGENT_NAME} من شركة {COMPANY_NAME}. "
            f"كيف حالك؟ "
            f"عندي سؤال بسيط على العقار اللي عندك في "
            f"{deal.get('location', 'المنطقة')}."
        )

    elif call_type == "broker":
        return (
            f"السلام عليكم أخوي، معك {AGENT_NAME} من شركة {COMPANY_NAME}. "
            f"تقدر تعطيني دقيقتين؟ "
            f"عندي صفقة تهمك في {deal.get('location', 'المنطقة')}."
        )

    elif call_type == "client":
        name     = deal.get("client_name", "")
        greeting = f"السلام عليكم {name}، " if name else "السلام عليكم، "
        return (
            f"{greeting}"
            f"معك {AGENT_NAME} من شركة {COMPANY_NAME}. "
            f"عندي خبر حلو — "
            f"لقينا لك عقار يطابق طلبك بالضبط في "
            f"{deal.get('location', 'المنطقة')}."
        )

    return f"السلام عليكم، معك {AGENT_NAME} من شركة {COMPANY_NAME}."