import { useState } from 'react'

const providers = [
  { id: 'chatgpt', label: 'ChatGPT', color: '#74aa9c' },
  { id: 'claude', label: 'Claude', color: '#d97757' },
  { id: 'gemini', label: 'Gemini', color: '#5578e5' },
  { id: 'grok', label: 'Grok', color: '#111111' },
  { id: 'deepseek', label: 'DeepSeek', color: '#4b6bff' },
]

const chromeCommand = 'google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-automation'
const apiExample = 'import requests\n\nresponse = requests.post(\n    "http://localhost:8000/api/ask",\n    json={"provider": "gemini", "prompt": "Hello"},\n)\nprint(response.json()["response"])'
const reactApiExample = `const response = await fetch('http://localhost:8000/api/ask', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ provider: 'gemini', prompt: 'Hello' }),
})

const data = await response.json()
console.log(data.response)`

function App() {
  const [provider, setProvider] = useState('chatgpt')
  const [prompt, setPrompt] = useState('')
  const [response, setResponse] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [status, setStatus] = useState('')
  const [isDarkMode, setIsDarkMode] = useState(() => localStorage.getItem('ai-assistant-theme') === 'dark')
  const [commandCopied, setCommandCopied] = useState(false)
  const [apiCopied, setApiCopied] = useState(false)
  const [reactApiCopied, setReactApiCopied] = useState(false)

  function toggleTheme() {
    setIsDarkMode((currentMode) => {
      const nextMode = !currentMode
      localStorage.setItem('ai-assistant-theme', nextMode ? 'dark' : 'light')
      return nextMode
    })
  }

  async function copyChromeCommand() {
    await navigator.clipboard.writeText(chromeCommand)
    setCommandCopied(true)
    window.setTimeout(() => setCommandCopied(false), 1800)
  }

  async function copyApiExample() {
    await navigator.clipboard.writeText(apiExample)
    setApiCopied(true)
    window.setTimeout(() => setApiCopied(false), 1800)
  }

  async function copyReactApiExample() {
    await navigator.clipboard.writeText(reactApiExample)
    setReactApiCopied(true)
    window.setTimeout(() => setReactApiCopied(false), 1800)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (!prompt.trim() || isLoading) return

    setIsLoading(true)
    setError('')
    setResponse('')
    setStatus('Working...')

    const statusTimer = provider === 'chatgpt'
      ? window.setInterval(async () => {
        try {
          const statusResult = await fetch('http://localhost:8000/api/status')
          if (statusResult.ok) setStatus((await statusResult.json()).status)
        } catch {
          // The request below shows the actionable connection error.
        }
      }, 1000)
      : null

    try {
      const result = await fetch('http://localhost:8000/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          prompt,
        }),
      })

      const data = await result.json()
      if (!result.ok) {
        throw new Error(data.detail || 'The request could not be completed.')
      }
      setResponse(data.response)
      setStatus('Response received')
    } catch (requestError) {
      setError(
        requestError instanceof TypeError
          ? 'Unable to reach the backend. Make sure FastAPI is running on port 8000.'
          : requestError.message,
      )
    } finally {
      if (statusTimer) window.clearInterval(statusTimer)
      setIsLoading(false)
    }
  }

  return (
    <main className={`app-shell ${isDarkMode ? 'dark-mode' : ''}`}>
      <section className="assistant-panel" aria-labelledby="page-title">
        <header className="app-header">
          <div className="brand-mark" aria-hidden="true">AI</div>
          <div>
            <p className="eyebrow">Ai api Box</p>
            <h1 id="page-title">Ask your assistant</h1>
          </div>
          <button className="theme-toggle" type="button" onClick={toggleTheme} aria-label={isDarkMode ? 'Use light mode' : 'Use dark mode'}>
            {isDarkMode ? '☼' : '☾'}
          </button>
        </header>
 <div className="command-bar">
          <code>{chromeCommand}</code>
          <button type="button" className="copy-command" onClick={copyChromeCommand}>
            {commandCopied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <form className="prompt-form" onSubmit={handleSubmit}>
          <fieldset className="provider-group">
            <legend>Choose a provider</legend>
            <div className="provider-options">
              {providers.map((option) => (
                <label className={`provider-option ${provider === option.id ? 'selected' : ''}`} key={option.id}>
                  <input
                    type="radio"
                    name="provider"
                    value={option.id}
                    checked={provider === option.id}
                    onChange={(event) => setProvider(event.target.value)}
                  />
                  <span className="provider-dot" style={{ '--provider-color': option.color }} />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <label className="prompt-label" htmlFor="prompt">Your prompt</label>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Enter your prompt..."
            rows="7"
          />
          <div className="form-footer">
            <span className="hint">{status || 'Local assistant'}</span>
            <button type="submit" disabled={!prompt.trim() || isLoading}>
              {isLoading ? 'Working...' : 'Send prompt'}
              <span aria-hidden="true">↗</span>
            </button>
          </div>
        </form>

        <section className="response-section" aria-live="polite" aria-labelledby="response-title">
          <div className="section-heading">
            <h2 id="response-title">Response</h2>
            {response && <span className="status-dot">Ready</span>}
          </div>
          <div className={`response-box ${response || error ? 'has-content' : ''}`}>
            {error ? <p className="error-message">{error}</p> : response ? <p>{response}</p> : <p className="empty-state">Your response will appear here.</p>}
          </div>
        </section>

        <section className="api-section" aria-labelledby="api-title">
          <div className="section-heading">
            <div>
              <p className="eyebrow">FastAPI endpoint</p>
              <h2 id="api-title">Connect another app</h2>
            </div>
            <code className="api-method">POST /api/ask</code>
          </div>
          <p className="api-description">Send a provider and prompt to use this assistant from another local app.</p>
          <div className="api-code-wrap">
            <pre><code>{apiExample}</code></pre>
            <button type="button" className="copy-api" onClick={copyApiExample}>
              {apiCopied ? 'Copied' : 'Copy code'}
            </button>
          </div>
          <p className="api-label">React / JavaScript</p>
          <div className="api-code-wrap">
            <pre><code>{reactApiExample}</code></pre>
            <button type="button" className="copy-api" onClick={copyReactApiExample}>
              {reactApiCopied ? 'Copied' : 'Copy code'}
            </button>
          </div>
        </section>
      </section>
      <p className="version-note">Local development · No external AI connection</p>
    </main>
  )
}

export default App
