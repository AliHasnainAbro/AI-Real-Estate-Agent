# 🏠 AI Real Estate Investment Agent

An intelligent, Saudi-Arabic-speaking AI agent that automates real estate deal matching and outbound calling. Built for the Saudi real estate market with native **Saudi Najdi dialect** enforcement.

## 🎯 Features

- **Intelligent Matching Engine**: Fuzzy-matches property inventory with client requests based on price, unit count, and ticket size
- **Autonomous Outbound Calling**: Makes SIP calls, listens to responses, transcribes Arabic audio, and maintains natural conversations
- **Saudi Dialect Enforcement**: Automatically detects and corrects formal Arabic (Fusha) drift, ensuring authentic Saudi Najdi communication
- **Multi-Scenario Support**: Handles owner verification, buyer outreach, and investor inquiries
- **Webhook Integration**: Make.com bridge for automation workflows
- **Offline STT**: Uses local Whisper for Arabic speech-to-text (no API key needed)
- **High-Quality TTS**: ElevenLabs with gTTS fallback for Arabic speech synthesis
- **Comprehensive Logging**: Full call transcripts, timestamps, and conversation history

## 🏗️ Architecture

```
Google Sheets (Inventory + Clients)
           ↓
   [Matching Engine] → call_queue.json
           ↓
  [Call Orchestrator] → Outbound SIP Calls
           ↓
  [Voice Pipeline] → STT + TTS
           ↓
   [LLM Brain (Groq)]
           ↓
  [Webhook Server] ← Make.com Integration
```

### Core Components

- **`matching_engine.py`**: Reads Google Sheets, fuzzy-matches deals with clients, outputs call queue
- **`call_orchestrator.py`**: Executes calls from the queue, manages the conversation loop
- **`llm_brain.py`**: Groq LLM integration with Saudi dialect enforcement and call-ending detection
- **`voice_pipeline.py`**: Whisper STT, ElevenLabs TTS, dialect drift detection
- **`webhook_server.py`**: FastAPI server for Make.com automation triggers
- **`system_prompts.py`**: System instructions for 3 different conversation scenarios
- **`test_pipeline.py`**: End-to-end testing utility

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- API keys for: Groq, ElevenLabs, Google Cloud (with Sheets access)
- Optional: Partner SIP provider (for outbound calls)

### 1. Clone & Setup Environment

```bash
git clone <your-repo>
cd AI-Real-Estate-Agent
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create `.env` File

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Then open `.env` and add your credentials (see **API Key Setup** section below).

### 3. Set Up Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create or select a project
3. Enable **Google Sheets API**
4. Create a **Service Account** JSON key
5. Download the JSON and save to: `config/service_account.json`

```bash
mkdir -p config
# Place your service_account.json here
```

### 4. Run Components

**Start the matching engine (runs once per schedule):**
```bash
python matching_engine.py
```

**Start the call orchestrator (processes call queue):**
```bash
python call_orchestrator.py
```

**Start the webhook server (for Make.com integration):**
```bash
uvicorn webhook_server:app --host 0.0.0.0 --port 8000
```

**Test end-to-end:**
```bash
python test_pipeline.py
```

---

## 🔑 API Key Setup

### Groq API (LLM Brain)
- **Provider**: [groq.com](https://console.groq.com)
- **Model Used**: `llama-3.3-70b-versatile` (free tier)
- **Key Name**: `GROQ_API_KEY`
- **Cost**: Free tier includes 100 API calls/minute indefinitely
- **Setup**:
  1. Sign up at https://console.groq.com
  2. Create API key in dashboard
  3. Add to `.env`: `GROQ_API_KEY=gsk_xxxxx...`

### ElevenLabs (Text-to-Speech)
- **Provider**: [elevenlabs.io](https://elevenlabs.io)
- **Key Name**: `ELEVENLABS_API_KEY`
- **Key Name**: `ELEVENLABS_VOICE_ID`
- **Cost**: Free tier has limited characters/month; paid plans start at $5/month
- **Setup**:
  1. Sign up at https://elevenlabs.io
  2. Get API key from settings
  3. Choose Arabic voice ID (e.g., Zahra for female, Almadi for male)
  4. Add to `.env`:
     ```
     ELEVENLABS_API_KEY=sk_xxxxx...
     ELEVENLABS_VOICE_ID=zahra  # or your chosen voice ID
     ```

### Google Sheets (Data Storage)
- **Provider**: [console.cloud.google.com](https://console.cloud.google.com)
- **Key Name**: `GOOGLE_SERVICE_ACCOUNT_FILE`
- **Key Name**: `GOOGLE_SHEET_ID`
- **Cost**: Free (up to 500 requests per 100 seconds)
- **Setup**:
  1. Create Google Cloud project
  2. Enable Google Sheets API
  3. Create Service Account → download JSON key
  4. Save JSON to `config/service_account.json`
  5. Get your Sheet ID from URL: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`
  6. Add to `.env`:
     ```
     GOOGLE_SHEET_ID=1a2b3c4d5e...
     GOOGLE_SERVICE_ACCOUNT_FILE=config/service_account.json
     ```

### Partner SIP Provider (Outbound Calls)
- **Examples**: Vapi, Bandwidth, Twilio
- **Key Name**: `PARTNER_API_BASE`, `PARTNER_API_KEY`, `SIP_CALLER_ID`
- **Setup**:
  1. Sign up with your preferred SIP provider
  2. Get API endpoint URL, API key, and a caller ID number
  3. Add to `.env`:
     ```
     PARTNER_API_BASE=https://api.example-sip.com
     PARTNER_API_KEY=sk_xxxxx...
     SIP_CALLER_ID=+966XXXXXXXXX  # Saudi number format
     ```

### Webhook Security (Make.com)
- **Key Name**: `WEBHOOK_SECRET`
- **Purpose**: Authenticates Make.com requests to prevent unauthorized access
- **Setup**:
  1. Generate a random secure string (e.g., use `openssl rand -hex 32`)
  2. Add to `.env`: `WEBHOOK_SECRET=your-random-secure-string`
  3. Paste the same value into your Make.com HTTP module header

---

## 📋 Complete `.env` File Template

```bash
# ════════════════════════════════════════════════════════════
# AI Real Estate Agent — Environment Variables
# ════════════════════════════════════════════════════════════

# ── GROQ LLM (Conversation Brain) ─────────────────────────
GROQ_API_KEY=gsk_xxxxx...

# ── ELEVENLABS (Text-to-Speech) ──────────────────────────
ELEVENLABS_API_KEY=sk_xxxxx...
ELEVENLABS_VOICE_ID=zahra  # or almadi, available Arabic voices

# ── GOOGLE SHEETS (Data Storage) ─────────────────────────
GOOGLE_SHEET_ID=1a2b3c4d5e...  # Your Google Sheet ID
GOOGLE_SERVICE_ACCOUNT_FILE=config/service_account.json

# ── PARTNER SIP PROVIDER (Outbound Calls) ───────────────
PARTNER_API_BASE=https://api.example-sip.com
PARTNER_API_KEY=sk_xxxxx...
SIP_CALLER_ID=+966XXXXXXXXX  # Your caller ID (Saudi number)

# ── WEBHOOK SECURITY (Make.com) ──────────────────────────
WEBHOOK_SECRET=your-random-secure-string-here

# ── OPTIONAL: Agent Identity ─────────────────────────────
AGENT_NAME=فهد  # Agent's Arabic name (default: "فهد")
COMPANY_NAME=الشركة  # Company Arabic name (default: "الشركة")
```

---

## 🧪 Testing

### Unit Test
Test individual components:
```bash
python test_pipeline.py
```

### Manual Call Test
Trigger a single call from the queue:
```bash
curl -X POST http://localhost:8000/trigger-call \
  -H "x-webhook-secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"queue_index": 0}'
```

### Webhook Health Check
```bash
curl http://localhost:8000/health
```

---

## 🔄 Integration with Make.com

### Scenario 1: Automatic Matching on New Data
```
Google Sheets (trigger on new row)
  ↓
Make.com Scenario 1
  ↓
POST /run-matching
  ↓
Matching Engine runs
  ↓
call_queue.json updated
```

### Scenario 2: Schedule Outbound Calls
```
Make.com Schedule (e.g., daily at 9am)
  ↓
POST /call-queue
  ↓
Call Orchestrator processes queue
```

### Scenario 3: Log Summary to Data Studio
```
GET /call-logs
  ↓
Returns JSONL call history
  ↓
Make.com sends to Google Data Studio
```

---

## 📊 File Structure

```
AI-Real-Estate-Agent/
├── call_orchestrator.py      # Outbound call manager
├── llm_brain.py              # Groq LLM + Saudi dialect logic
├── matching_engine.py        # Fuzzy-match deals ↔ clients
├── voice_pipeline.py         # STT + TTS + dialect detection
├── webhook_server.py         # Make.com HTTP bridge
├── system_prompts.py         # System instructions (3 scenarios)
├── test_pipeline.py          # End-to-end testing
├── requirements.txt          # Python dependencies
├── .env.example              # Template for environment variables
├── README.md                 # This file
├── data/
│   └── call_queue.json       # Pending calls (auto-generated)
├── logs/
│   └── call_logs.jsonl       # Call transcripts + metadata
└── config/
    └── service_account.json  # Google service account (not in repo)
```

---

## 🛠️ Troubleshooting

### Issue: `GROQ_API_KEY not set in .env`
**Solution**: Ensure `GROQ_API_KEY` is in your `.env` file and `load_dotenv()` was called.

### Issue: `Whisper model fails to load`
**Solution**: Install `faster-whisper` explicitly:
```bash
pip install faster-whisper
```

### Issue: Call doesn't play audio
**Solution**: Check `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` are correct. Verify gTTS fallback works:
```python
from gtts import gTTS
gTTS("مرحبا", lang="ar").save("test.mp3")
```

### Issue: Google Sheets connection fails
**Solution**: 
1. Verify `service_account.json` exists at `config/service_account.json`
2. Verify `GOOGLE_SHEET_ID` is correct (from URL)
3. Share the Google Sheet with the service account email (in the JSON file)

### Issue: Make.com webhook returns 401 Unauthorized
**Solution**: Ensure the `x-webhook-secret` header in Make.com matches your `.env` `WEBHOOK_SECRET` value exactly.

---

## 📞 Support & Customization

- **Matching Tolerance**: Edit `PRICE_TOLERANCE`, `UNIT_TOLERANCE`, etc. in `matching_engine.py`
- **System Prompts**: Modify conversation behavior in `system_prompts.py`
- **Dialect Rules**: Add/remove Saudi dialect mappings in `voice_pipeline.py`
- **Call Limits**: Change `MAX_TURNS` in `call_orchestrator.py`

---
