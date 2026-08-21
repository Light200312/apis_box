import { useState } from 'react'

const providers = [
  { id: 'chatgpt', label: 'ChatGPT', color: '#74aa9c' },
  { id: 'claude', label: 'Claude', color: '#d97757' },
  { id: 'gemini', label: 'Gemini', color: '#5578e5' },
  { id: 'grok', label: 'Grok', color: '#111111' },
  { id: 'deepseek', label: 'DeepSeek', color: '#4b6bff' },
]

function App() {
  const [provider, setProvider] = useState('chatgpt')
  const [prompt, setPrompt] = useState('')
  const [response, setResponse] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [status, setStatus] = useState('')

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
        body: JSON.stringify({ provider, prompt }),
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
    <main className="app-shell">
      <section className="assistant-panel" aria-labelledby="page-title">
        <header className="app-header">
          <div className="brand-mark" aria-hidden="true">AI</div>
          <div>
            <p className="eyebrow">Step 01 / Local assistant</p>
            <h1 id="page-title">Ask your assistant</h1>
          </div>
        </header>

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
      </section>
      <p className="version-note">Local development · No external AI connection</p>
    </main>
  )
}

export default App
