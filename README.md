# AI Automation Assistant

Step 1 is a local React + Vite frontend with a FastAPI backend. AI providers return mock responses only; browser automation is intentionally not included yet.

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload --port 8000
```

## Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Step 2: ChatGPT browser automation

ChatGPT requests use a dedicated persistent profile at `~/.ai-automation-chrome/`.
The first ChatGPT request opens a headed Chromium window. Complete login or any
CAPTCHA manually in that window; credentials and tokens are never handled by
this application. Later ChatGPT requests reuse the same browser context and tab.

Claude and Gemini remain mock responses until their browser adapters are added.

To verify the flow:

1. Start the backend and frontend using the commands above.
2. Select ChatGPT, enter a prompt, and click **Send prompt**.
3. If the browser opens to login, complete login manually and return to the browser window.
4. Wait for `Login detected. Continuing...`, then confirm the response appears in the frontend.
5. Send a second ChatGPT prompt and confirm the existing browser window and ChatGPT tab are reused.
6. Confirm no second Chrome window or duplicate ChatGPT tab is created.

The backend status can also be checked at http://localhost:8000/api/status.
