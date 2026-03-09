# ============================================================
# voice_pipeline.py
# ─────────────────────────────────────────────────────────
# HANDLES:
#   STT → local Whisper (free, runs offline, no API key)
#   TTS → ElevenLabs free tier (best quality)
#         gTTS fallback (unlimited free, lower quality)
#   Dialect drift detection + auto-correction
# ============================================================

import os
import io
import aiohttp
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")

# ── Load Whisper model once at import time ────────────────────
# This prevents re-loading on every call (slow + memory waste)
print("⏳ Loading Whisper STT model (first run takes ~30 seconds)...")
try:
    from faster_whisper import WhisperModel
    # "medium" gives best Arabic accuracy without GPU
    # Use "small" if you're low on RAM (< 8GB)
    whisper_model = WhisperModel(
        "medium",
        device="cpu",
        compute_type="int8"   # int8 = faster on CPU, same accuracy
    )
    print("✅ Whisper STT ready")
except Exception as e:
    whisper_model = None
    print(f"⚠️  Whisper failed to load: {e}")
    print("   STT will be unavailable — install faster-whisper")


# ── SPEECH TO TEXT ────────────────────────────────────────────
def transcribe_audio(audio_bytes: bytes) -> str:
    """
    Convert caller's audio bytes → Arabic text string.
    Uses local Whisper — completely offline, no API cost.

    Returns empty string if:
    - audio is too short (silence)
    - transcription fails
    - Whisper not loaded
    """
    if not whisper_model:
        print("⚠️  Whisper not available — cannot transcribe")
        return ""

    if len(audio_bytes) < 200:
        return ""  # Too short — definitely silence

    try:
        audio_buffer = io.BytesIO(audio_bytes)
        segments, _ = whisper_model.transcribe(
            audio_buffer,
            language="ar",
            vad_filter=True,                    # strips silence
            vad_parameters={"min_silence_duration_ms": 400}
        )
        text = " ".join(seg.text for seg in segments).strip()
        return text

    except Exception as e:
        print(f"⚠️  Transcription error: {e}")
        return ""


# ── TEXT TO SPEECH (ElevenLabs) ───────────────────────────────
async def synthesize_elevenlabs(text: str) -> bytes | None:
    """
    Convert text → audio using ElevenLabs API.
    Free tier: 10,000 characters/month.
    Returns MP3 bytes or None if failed/quota exceeded.
    """
    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        return None  # Not configured — skip to fallback

    url = (f"https://api.elevenlabs.io/v1/text-to-speech/"
           f"{ELEVENLABS_VOICE_ID}")

    headers = {
        "xi-api-key":   ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    }

    # Voice settings tuned for natural Arabic call quality
    payload = {
        "text":     text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability":         0.60,
            "similarity_boost":  0.85,
            "style":             0.25,
            "use_speaker_boost": True,
        },
    }

    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload,
                                 headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=10)
                                 ) as resp:
                if resp.status == 200:
                    return await resp.read()
                elif resp.status == 429:
                    print("⚠️  ElevenLabs quota reached → fallback to gTTS")
                    return None
                else:
                    err = await resp.text()
                    print(f"⚠️  ElevenLabs {resp.status}: {err[:100]}")
                    return None

    except aiohttp.ClientError as e:
        print(f"⚠️  ElevenLabs network error: {e}")
        return None


# ── TEXT TO SPEECH (gTTS fallback) ───────────────────────────
async def synthesize_gtts(text: str) -> bytes:
    """
    Free unlimited TTS fallback using Google Text-to-Speech.
    Lower voice quality but no character limit.
    Requires internet connection (but no API key).
    """
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="ar", slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        audio = buf.read()
        print(f"   gTTS generated {len(audio)} bytes")
        return audio
    except Exception as e:
        print(f"❌ gTTS failed: {e}")
        return b""


# ── MAIN TTS ROUTER ───────────────────────────────────────────
async def synthesize_speech(text: str) -> bytes:
    """
    Primary TTS function — try ElevenLabs first, fall back to gTTS.
    Always returns bytes (may be empty if all methods fail).
    """
    if not text or not text.strip():
        return b""

    # Try ElevenLabs (best quality)
    audio = await synthesize_elevenlabs(text)
    if audio and len(audio) > 100:
        return audio

    # Fallback: gTTS (free, unlimited)
    print("🔄 Using gTTS fallback...")
    return await synthesize_gtts(text)


# ── DIALECT DRIFT DETECTION ───────────────────────────────────
# These are Fusha (Formal Arabic) markers that should NEVER
# appear in the agent's Saudi dialect responses.
FUSHA_MARKERS = [
    "يسعدني", "بكل سرور", "بالتأكيد", "يمكنني",
    "أريد أن", "لديّ", "لديك", "هذا الأمر",
    "سأقوم", "سوف أقوم", "ماذا", "إنني",
    "حيث إن", "وذلك", "بناءً على", "نظراً لـ",
    "للتواصل معكم", "في انتظار",
]

# Direct Fusha → Saudi substitutions
DIALECT_FIXES = {
    "يسعدني":   "يسرني",
    "بالتأكيد": "أكيد",
    "يمكنني":   "أقدر",
    "أريد":     "أبغى",
    "لديّ":     "عندي",
    "لدي":      "عندي",
    "سأقوم":    "بسوي",
    "سوف أ":    "بـ",
    "ماذا":     "وش",
    "إنني":     "أنا",
    "كيف يمكن": "كيف تقدر",
    "هل تستطيع": "تقدر",
}


def check_dialect_drift(text: str) -> bool:
    """
    Returns True if Fusha markers are detected in the text.
    Used to flag LLM responses before sending to TTS.
    """
    return any(marker in text for marker in FUSHA_MARKERS)


def fix_dialect_drift(text: str) -> str:
    """
    Apply direct substitutions to patch Fusha → Saudi dialect.
    Used as last resort when LLM retry doesn't fix drift.
    """
    for fusha, saudi in DIALECT_FIXES.items():
        text = text.replace(fusha, saudi)
    return text