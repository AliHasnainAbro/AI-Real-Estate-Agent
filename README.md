# AI-Real-Estate-Agent

## Run locally

1. Create a virtual environment.
2. Install dependencies:
	- `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in the values.
4. Put your Google service account JSON at `config/service_account.json`.
5. Run the pieces you need:
	- `python matching_engine.py`
	- `python call_orchestrator.py`
	- `uvicorn webhook_server:app --host 0.0.0.0 --port 8000`
	- `python test_pipeline.py`

## Required environment variables

- `GROQ_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `GOOGLE_SHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_FILE`
- `PARTNER_API_BASE`
- `PARTNER_API_KEY`
- `SIP_CALLER_ID`
- `WEBHOOK_SECRET`
- `AGENT_NAME` and `COMPANY_NAME` are optional
