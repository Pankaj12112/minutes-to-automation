# Meeting Intelligence Pipeline

A modular FastAPI backend that processes meeting audio, generates a **diarized transcript**, extracts **structured action items** with GPT-4o (OpenAI Structured Outputs), and dispatches notifications via **webhook** (n8n/Make) or **SMTP email**.

## Architecture

```
Audio Upload (.mp3/.wav)
        │
        ▼
Transcription Service (AssemblyAI or Deepgram, speaker diarization ON)
        │
        ▼
LLM Processor (GPT-4o + Pydantic schema validation)
        │
        ▼
Notifier (Webhook JSON payload and/or per-task SMTP emails)
```

## Project Structure

```
.
├── main.py
├── config.py
├── requirements.txt
├── .env.example
├── README.md
└── services/
    ├── __init__.py
    ├── transcription.py
    ├── llm_processor.py
    └── notifier.py
```

## Prerequisites

- Python 3.10+
- API keys for:
  - OpenAI
  - AssemblyAI **or** Deepgram (depending on `TRANSCRIPTION_PROVIDER`)
- A webhook URL (n8n/Make) and/or SMTP credentials for notifications

## Installation

1. Create and activate a virtual environment:

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables:

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

Edit `.env` with your real API keys and notification settings.

## Run the Server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## API Endpoints

### `GET /health`

Returns service health and configured providers.

### `POST /process-meeting`

Upload a meeting audio file and run the full pipeline.

**Form field:** `audio` (multipart file upload)

**Example (curl):**

```bash
curl -X POST "http://localhost:8000/process-meeting" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "audio=@/path/to/meeting.mp3;type=audio/mpeg"
```

**Sample response shape:**

```json
{
  "job_id": "uuid",
  "transcript": "Speaker A: We need to update the database schema.\nSpeaker B: I'll handle it by Friday.",
  "utterances": [
    {"speaker": "Speaker A", "text": "We need to update the database schema."},
    {"speaker": "Speaker B", "text": "I'll handle it by Friday."}
  ],
  "analysis": {
    "meeting_summary": "...",
    "action_items": [
      {
        "detected_name": "Bob Smith",
        "resolved_email": "bob@company.com",
        "task_description": "Update the database schema",
        "priority": "High",
        "timeline": "By Friday"
      }
    ]
  },
  "notifications": {
    "mode": "webhook",
    "webhook": {"status_code": 200, "response_text": "..."},
    "emails": []
  }
}
```

## Configuration Notes

| Variable | Description |
|---|---|
| `TRANSCRIPTION_PROVIDER` | `assemblyai` (default) or `deepgram` |
| `CONTACT_DIRECTORY_JSON` | JSON map of names to office emails for LLM resolution |
| `NOTIFICATION_MODE` | `webhook`, `email`, or `both` |
| `WEBHOOK_URL` | Automation endpoint that receives the full structured JSON |
| `SMTP_*` | Required when sending direct email notifications |

## Switching Transcription Providers

Set in `.env`:

```env
TRANSCRIPTION_PROVIDER=deepgram
DEEPGRAM_API_KEY=your-key
```

Both providers run with **speaker diarization enabled** and return lines formatted as `Speaker X: ...`.

## Error Handling

External API failures (transcription, OpenAI, webhook, SMTP) are wrapped with descriptive logging and returned as HTTP `502 Bad Gateway` responses with clear error messages.
