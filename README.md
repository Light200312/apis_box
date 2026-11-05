# AI API Box

AI API Box is a local assistant that exposes a simple FastAPI endpoint while using browser sessions for provider access. A React + Vite interface lets you choose a provider, send a prompt, view the response, switch themes, and copy integration examples.

Supported providers:

- ChatGPT
- Claude
- Gemini
- Grok
- DeepSeek

The provider adapters connect to tabs that are already open in Chrome through the Chrome DevTools Protocol (CDP). This keeps login sessions in the user's browser and avoids storing provider credentials in the application.

## How It Works

```text
React frontend -> FastAPI /api/ask -> Playwright over CDP -> Provider browser tab
```

The backend reuses one connected Chrome context. Before making a request, open the provider's website in that Chrome profile and sign in manually.

## Requirements

- Python 3.10 or newer
- Node.js and npm
- Google Chrome installed as `google-chrome`
- A Chrome profile with provider sessions logged in

## Setup

### 1. Install backend dependencies

From the project root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Start automation Chrome

Use a dedicated profile and remote debugging port:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-automation
```

In that Chrome window, open and sign in to the provider you want to use:

- https://chatgpt.com
- https://claude.ai
- https://gemini.google.com
- https://grok.com
- https://chat.deepseek.com

Keep the browser running while using the application.

### 3. Start the FastAPI backend

In the `backend` directory with the virtual environment activated:

```bash
uvicorn main:app --reload --port 8000
```

The backend is available at http://localhost:8000.

Useful endpoints:

- `GET /api/status` checks the Chrome connection state.
- `POST /api/ask` sends a prompt to a selected provider.
- `POST /v1/messages` is a local, text-only Anthropic Messages compatibility adapter.
- `GET /docs` opens the interactive FastAPI documentation.

### 4. Start the React frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## Using the Interface

1. Start Chrome, the backend, and the frontend.
2. Select a provider whose tab is open and logged in.
3. Enter a prompt and choose **Send prompt**.
4. Wait for the response to appear.
5. Use the sun/moon control to switch between light and dark mode.
6. Use the command and API copy buttons when integrating another local app.

## API Usage

### Python

```python
import requests

response = requests.post(
		"http://localhost:8000/api/ask",
		json={"provider": "gemini", "prompt": "Hello"},
)
response.raise_for_status()
print(response.json()["response"])
```

### React or JavaScript

```javascript
const response = await fetch('http://localhost:8000/api/ask', {
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify({ provider: 'gemini', prompt: 'Hello' }),
})

const data = await response.json()
if (!response.ok) throw new Error(data.detail || 'Request failed')
console.log(data.response)
```

The `provider` value must be one of `chatgpt`, `claude`, `gemini`, `grok`, or `deepseek`.

Example response:

```json
{
	"provider": "gemini",
	"response": "Hello! How can I help you?"
}
```

## Claude Code compatibility adapter

`POST /v1/messages` keeps `/api/ask` intact and routes Messages requests to the
existing Claude browser automation first. It makes at most one ChatGPT fallback
attempt only when Claude fails *before* the prompt can be submitted. The
`x-apis-box-provider` response header records which provider produced the
answer. If Claude may already have received the prompt, fallback is suppressed
and the request returns an error instead of risking duplicate work.

The adapter accepts text messages and returns the Anthropic Messages response
shape. It also emits the standard SSE event sequence when `"stream": true`,
but browser automation only exposes an answer after the provider page finishes
generating it. Therefore the response is sent as one final text delta, not live
token streaming. Token counts are `0`, because browser automation cannot report
provider token accounting.

It does **not** support native `tool_use`, image/document inputs, or forced
tool calls. Claude Code 2.1.309 is installed in this workspace and normally
sends tool definitions for coding-agent work. This adapter can serve plain-text
Messages clients, but it cannot safely power autonomous file edits, terminal
commands, or reliable Claude Code coding-agent loops through browser sessions.
Use an official/provider API-compatible service for that workflow.

To test the adapter after starting Chrome and the backend:

```bash
curl http://127.0.0.1:8000/v1/messages \
  --header 'content-type: application/json' \
  --header 'x-api-key: local-browser-adapter' \
  --data '{
    "model": "claude-browser",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": "Reply with one word: hello"}]
  }'
```

The installed VS Code extension (`anthropic.claude-code` 2.1.309) supports
environment variables through its settings. If you want to experiment with the
text-only adapter, add the following to VS Code **User Settings (JSON)** and
restart the Claude Code session:

```json
{
  "claudeCode.environmentVariables": [
    { "name": "ANTHROPIC_BASE_URL", "value": "http://127.0.0.1:8000" },
    { "name": "ANTHROPIC_AUTH_TOKEN", "value": "local-browser-adapter" }
  ],
  "claudeCode.disableLoginPrompt": true
}
```

`ANTHROPIC_BASE_URL` deliberately points to the server root: Claude Code adds
`/v1/messages` itself. The opaque token is expected by Claude Code but is not
validated or forwarded by this local server. Keep the FastAPI service and Chrome DevTools endpoint
bound to loopback (`127.0.0.1`); do not expose port `9222` or this adapter to
your network.

## Troubleshooting

### Chrome is unavailable

Confirm that Chrome was started with port `9222` and the dedicated profile:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-automation
```

Also verify that the browser is still running and that the backend can reach http://127.0.0.1:9222.

### No provider tab was found

Open the provider website in the automation Chrome window. The application does not create provider tabs automatically for these integrations.

### Provider requires login

Complete login manually in the connected Chrome window, then retry the request. The application does not receive or store passwords, cookies, or API keys.

### A response fails or times out

Provider websites can change their DOM. Check the backend terminal for Playwright diagnostics, confirm the provider tab is responsive, and retry with a fresh provider page if needed.

## Testing

Run the focused automation tests from `backend`:

```bash
source .venv/bin/activate
pytest -q test_claude_automation.py test_gemini_automation.py test_grok_automation.py test_deepseek_automation.py
```

The Messages adapter has focused protocol and fallback tests as well:

```bash
pytest -q test_anthropic_adapter.py
```

Compile the backend modules:

```bash
python -m compileall .
```

Build the frontend:

```bash
cd ../frontend
npm run build
```
