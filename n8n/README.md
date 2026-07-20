# n8n Setup for Meeting Action Items

This workflow receives JSON from the FastAPI pipeline and sends one email per action item.

## What the webhook receives

```json
{
  "meeting_summary": "Team discussed sprint priorities...",
  "action_items": [
    {
      "detected_name": "Yash",
      "resolved_email": "work.yashthorat29@gmail.com",
      "task_description": "Update the database schema",
      "priority": "High",
      "timeline": "By Friday"
    }
  ]
}
```

## Step 1 — Run n8n

**Option A: Docker (recommended)**

```bash
docker run -it --rm --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n n8nio/n8n
```

**Option B: n8n Cloud**

Use [https://n8n.io](https://n8n.io) and skip local Docker.

Open the editor at [http://localhost:5678](http://localhost:5678).

## Step 2 — Import the workflow

1. In n8n, click **Workflows → Import from File**
2. Select `n8n/meeting-actions-workflow.json`
3. Open the imported workflow **Meeting Action Items Pipeline**

## Step 3 — Configure Gmail SMTP credentials

The **Send Email** node needs SMTP credentials.

1. In n8n: **Credentials → Add credential → SMTP**
2. Use Gmail settings:

| Field | Value |
|---|---|
| Host | `smtp.gmail.com` |
| Port | `465` (recommended in Docker) or `587` |
| User | `work.yashthorat29@gmail.com` |
| Password | Your Gmail **App Password** (16 characters, no spaces) |
| SSL/TLS | **ON** for port `465` · **STARTTLS** for port `587` |

Create a Gmail App Password: Google Account → Security → 2-Step Verification → App passwords → create one for **Mail**.

3. Open the **Send Email** node and select your SMTP credential
4. Set **From Email** to `work.yashthorat29@gmail.com`

### If you see `ENETUNREACH` or "Couldn't connect with these settings"

This usually means n8n (especially in Docker) cannot reach Gmail over **IPv6**.

Try in this order:

1. **Switch to port 465 with SSL/TLS enabled** (not STARTTLS)
2. **Retry** the credential test
3. If it still fails, restart n8n with IPv6 disabled:

```powershell
docker stop n8n
docker rm n8n
docker run -it --rm --name n8n -p 5678:5678 `
  --sysctl net.ipv6.conf.all.disable_ipv6=1 `
  -v n8n_data:/home/node/.n8n n8nio/n8n
```

4. Still failing? Use **n8n Cloud** ([n8n.io](https://n8n.io)) instead of local Docker — SMTP works more reliably there.

**App password checklist:**
- 2-Step Verification must be ON on your Google account
- Use the 16-character app password, not your normal Gmail password
- Remove any spaces when pasting (e.g. `abcd efgh ijkl mnop` → `abcdefghijklmnop`)

## Step 4 — Activate and copy the webhook URL

1. Click **Activate** (top-right toggle)
2. Open the **Webhook** node
3. Copy the **Production URL**, e.g.:
   - Local: `http://localhost:5678/webhook/meeting-actions`
   - n8n Cloud: `https://your-name.app.n8n.cloud/webhook/meeting-actions`

4. Paste it into your project `.env`:

```env
WEBHOOK_URL=http://localhost:5678/webhook/meeting-actions
NOTIFICATION_MODE=webhook
```

## Step 5 — Test end-to-end

**Terminal 1 — n8n** (if using Docker, already running)

**Terminal 2 — FastAPI**

```powershell
cd C:\Users\djrob\Downloads\AICTE
.venv\Scripts\activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 3 — Send a test webhook directly to n8n**

```powershell
curl -X POST "http://localhost:5678/webhook/meeting-actions" `
  -H "Content-Type: application/json" `
  -d "{\"meeting_summary\":\"Sprint planning call\",\"action_items\":[{\"detected_name\":\"Yash\",\"resolved_email\":\"work.yashthorat29@gmail.com\",\"task_description\":\"Deploy API changes to staging\",\"priority\":\"High\",\"timeline\":\"Tomorrow\"}]}"
```

You should see an execution in n8n and an email in the inbox.

**Then test the full pipeline with audio:**

```powershell
curl -X POST "http://localhost:8000/process-meeting" `
  -F "audio=@C:\path\to\meeting.wav"
```

## Workflow diagram

```
Webhook (POST /meeting-actions)
    → Parse Action Items (Code)
    → Has Action Items? (IF)
         ├─ yes → Send Email (SMTP) → Respond Success
         └─ no  → Respond No Items
```

## Troubleshooting

| Issue | Fix |
|---|---|
| Webhook 404 | Workflow must be **Activated**; use Production URL, not Test URL |
| SMTP auth failed | Use a Gmail App Password, not your regular password |
| No emails but 200 OK | Check n8n **Executions** tab for node errors |
| FastAPI 502 on webhook | Confirm n8n is running and `WEBHOOK_URL` matches exactly |

## Security note

If API keys were shared in chat or committed anywhere, rotate them in the OpenAI and Deepgram dashboards and update `.env`.
