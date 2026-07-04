import { useState } from 'react'

import { searchLogs, explainError } from '../api'

const LogExplorer = () => {
  const [query, setQuery] = useState('')
  const [serviceId, setServiceId] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Explain state
  const [explaining, setExplaining] = useState(false)
  const [explanation, setExplanation] = useState(null)
  const [explainError_, setExplainError] = useState('')

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    if (!serviceId.trim()) {
      setError('service_id is required for semantic search (e.g. checkout-api, payments-api).')
      return
    }

    setLoading(true)
    setError('')
    setExplanation(null)

    try {
      const data = await searchLogs(query, serviceId.trim(), 10)
      setResults(data)
    } catch (err) {
      setError(err.message || 'Search failed. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  const handleExplain = async (message) => {
    setExplaining(true)
    setExplainError('')
    setExplanation(null)

    try {
      const data = await explainError(message, serviceId)
      setExplanation(data)
    } catch (err) {
      setExplainError(err.message || 'Explain failed.')
    } finally {
      setExplaining(false)
    }
  }

  const getLevelClass = (level) => {
    if (level === 'ERROR') return 'text-red-400'
    if (level === 'WARN') return 'text-amber-400'
    if (level === 'INFO') return 'text-emerald-400'
    return 'text-neutral-400'
  }

  const getScoreColor = (score) => {
    if (score >= 0.75) return 'text-emerald-400'
    if (score >= 0.5) return 'text-amber-400'
    return 'text-neutral-400'
  }

  return (
    <div className="space-y-6">
      {/* Semantic Search Bar */}
      <div className="bg-neutral-950 rounded-3xl border border-neutral-800 p-8">
        <h2 className="text-2xl font-bold text-cyan-400 mb-4">Semantic Search</h2>
        <p className="text-sm text-neutral-500 mb-6">
          Search logs by meaning, not keywords. Try: "database connection timeout" or "payment checkout failure".
        </p>

        <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Natural language query..."
            className="flex-1 bg-black/40 border border-neutral-700 rounded-xl px-4 py-3 text-white placeholder-neutral-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/30"
          />
          <input
            type="text"
            value={serviceId}
            onChange={(e) => setServiceId(e.target.value)}
            placeholder="service_id (required, e.g. checkout-api)"
            required
            className="sm:w-56 bg-black/40 border border-neutral-700 rounded-xl px-4 py-3 text-white placeholder-neutral-600 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/30"
          />
          <button
            type="submit"
            disabled={loading || !query.trim() || !serviceId.trim()}
            className="px-6 py-3 rounded-xl bg-cyan-500/90 hover:bg-cyan-400 text-neutral-950 font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </form>

        {error && <div className="text-red-400 text-sm mt-4">{error}</div>}
      </div>

      {/* Search Results */}
      {results.length > 0 && (
        <div className="bg-neutral-950 rounded-3xl border border-neutral-800 p-8">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-2xl font-bold text-cyan-400">Search Results</h2>
            <span className="text-sm text-neutral-500">{results.length} matches</span>
          </div>

          <div className="space-y-3">
            {results.map((log, i) => {
              const p = log.payload || log
              const message = p.message || ''
              const level = p.level || 'UNKNOWN'
              const svc = p.service_id || p.service || 'unknown'
              const score = log.score != null ? log.score : 0
              return (
                <div
                  key={i}
                  className="bg-black/40 border border-white/5 rounded-2xl px-5 py-4 flex items-start gap-4"
                >
                  <span className={`text-xs font-mono mt-1 ${getScoreColor(score)}`}>
                    {(score * 100).toFixed(0)}%
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={getLevelClass(level)}>{level}</span>
                      <span className="text-neutral-500 text-sm">({svc})</span>
                      {p.timestamp && (
                        <span className="text-neutral-600 text-xs">{p.timestamp}</span>
                      )}
                    </div>
                    <code className="block text-sm font-mono text-neutral-300 break-words">
                      {message}
                    </code>
                  </div>
                  <button
                    onClick={() => handleExplain(message)}
                    disabled={explaining}
                    className="shrink-0 px-3 py-1.5 rounded-lg bg-indigo-500/20 hover:bg-indigo-500/40 border border-indigo-500/30 text-indigo-300 text-xs font-medium disabled:opacity-40 transition-all"
                  >
                    {explaining ? '...' : 'Explain'}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Explain Result */}
      {explanation && (
        <div className="bg-neutral-950 rounded-3xl border border-indigo-900/40 p-8">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-2xl font-bold text-indigo-400">AI Root Cause Analysis</h2>
            <span className="text-xs text-neutral-500 bg-black/40 px-3 py-1 rounded-full">
              {explanation.model}
            </span>
          </div>

          {explanation.context_logs?.length > 0 && (
            <div className="mb-4 text-xs text-neutral-500">
              Based on {explanation.context_logs.length} context log(s) from Qdrant
            </div>
          )}

          <div className="bg-black/40 border border-white/5 rounded-2xl p-5 text-neutral-300 leading-7 whitespace-pre-wrap text-sm">
            {explanation.explanation}
          </div>
        </div>
      )}

      {explainError_ && (
        <div className="bg-red-950/40 border border-red-900/40 rounded-3xl p-6 text-red-400 text-sm">
          {explainError_}
        </div>
      )}

      {explaining && !explanation && (
        <div className="bg-neutral-950 rounded-3xl border border-indigo-900/40 p-8">
          <div className="flex items-center gap-3 text-indigo-400">
            <span className="animate-spin">⟳</span>
            <span className="text-sm">Generating root cause analysis via GLM...</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default LogExplorer
