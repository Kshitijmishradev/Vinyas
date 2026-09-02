import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { ApiError, analysisResults, analysisStatus, cancelAnalysis, explainFinding, normalizeGitHubRepositoryUrl, serverHealth, startAnalysis, startLocalAnalysis } from './api'
import { DependencyGraph } from './components/DependencyGraph'
import type { FileNode, Finding, Graph, Health, Job } from './types'
import { LandingPage } from './LandingPage'

type Tab = 'overview' | 'findings' | 'files' | 'graph'

function AnalyzerApp() {
  const [health, setHealth] = useState<Health | null>(null)
  const [repositoryUrl, setRepositoryUrl] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [graph, setGraph] = useState<Graph | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [tab, setTab] = useState<Tab>('overview')
  const [query, setQuery] = useState('')
  const [rule, setRule] = useState('all')
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [formError, setFormError] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [cancelRequested, setCancelRequested] = useState(false)
  const [explanation, setExplanation] = useState<{ text: string; ai: boolean } | null>(null)
  const repositoryInput = useRef<HTMLInputElement>(null)
  const jobId = job?.id
  const jobStatus = job?.status

  useEffect(() => {
    serverHealth().then(setHealth).catch(() => setError('Cannot connect to the Vinyas API.'))
  }, [])

  useEffect(() => {
    const analysisId = new URLSearchParams(window.location.search).get('analysis')
    if (!analysisId) return
    let active = true
    async function restore() {
      try {
        const current = await analysisStatus(analysisId as string)
        if (!active) return
        setJob(current)
        if (current.source?.kind === 'github') setRepositoryUrl(current.source.repository_url)
        if (current.status === 'complete') {
          const result = await analysisResults(current.id)
          if (!active) return
          setGraph(result.graph)
          setFindings(result.findings)
        }
      } catch (cause) {
        if (!active) return
        if (cause instanceof ApiError && [404, 410].includes(cause.status)) setUnavailable(true)
        else setError(errorMessage(cause, 'Could not restore this analysis.'))
      }
    }
    void restore()
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!jobId || !jobStatus || !['queued', 'running'].includes(jobStatus)) return
    const timer = window.setInterval(async () => {
      try {
        const current = await analysisStatus(jobId)
        setJob(current)
        if (current.source?.kind === 'github') setRepositoryUrl(current.source.repository_url)
        if (current.status === 'complete') {
          const result = await analysisResults(current.id)
          setGraph(result.graph)
          setFindings(result.findings)
          setTab('overview')
        }
      } catch (cause) {
        setError(errorMessage(cause, 'Analysis status failed'))
      }
    }, 700)
    return () => window.clearInterval(timer)
  }, [jobId, jobStatus])

  async function analyze(event?: React.FormEvent) {
    event?.preventDefault()
    let canonical: string
    try {
      canonical = normalizeGitHubRepositoryUrl(repositoryUrl)
    } catch (cause) {
      setFormError(errorMessage(cause, 'Enter a valid GitHub repository URL.'))
      repositoryInput.current?.focus()
      return
    }
    setError(''); setFormError(''); setUnavailable(false); setCancelRequested(false)
    setGraph(null); setFindings([]); setSelectedFinding(null); setSelectedFile(null); setExplanation(null)
    try {
      const created = await startAnalysis(canonical)
      setJob(created)
      setRepositoryUrl(canonical)
      window.history.replaceState(null, '', `/app?analysis=${created.id}`)
    } catch (cause) {
      setError(errorMessage(cause, 'Analysis failed'))
    }
  }

  async function cancel() {
    if (!job) return
    await cancelAnalysis(job.id)
    setCancelRequested(true)
    setJob({ ...job, message: 'Cancellation requested' })
  }

  async function analyzeLocal() {
    setError(''); setGraph(null); setFindings([]); setSelectedFinding(null); setSelectedFile(null)
    try {
      const created = await startLocalAnalysis()
      setJob(created)
      window.history.replaceState(null, '', `/app?analysis=${created.id}`)
    } catch (cause) {
      setError(errorMessage(cause, 'Analysis failed'))
    }
  }

  function reset() {
    setJob(null); setGraph(null); setFindings([]); setSelectedFinding(null); setSelectedFile(null)
    setExplanation(null); setError(''); setFormError(''); setUnavailable(false); setCancelRequested(false)
    window.history.replaceState(null, '', '/app')
    window.setTimeout(() => repositoryInput.current?.focus(), 0)
  }

  const filteredFindings = useMemo(() => findings.filter((finding) => {
    const matchesRule = rule === 'all' || finding.rule === rule
    const text = `${finding.path} ${finding.message} ${finding.evidence}`.toLowerCase()
    return matchesRule && text.includes(query.toLowerCase())
  }), [findings, query, rule])
  const rules = useMemo(() => [...new Set(findings.map((finding) => finding.rule))].sort(), [findings])
  const files = useMemo(() => [...(graph?.files || [])].sort((a, b) => b.metrics.fan_out - a.metrics.fan_out || a.path.localeCompare(b.path)), [graph])
  const selectedFileNode = graph?.files.find((file) => file.path === selectedFile) || null
  const relatedEdges = graph?.edges.filter((edge) => edge.source === selectedFile || edge.target === selectedFile) || []
  const busy = job?.status === 'queued' || job?.status === 'running'
  const githubSource = job?.source?.kind === 'github' ? job.source : graph?.source?.kind === 'github' ? graph.source : null
  const sourceLabel = githubSource
    ? `${githubSource.owner}/${githubSource.repository}${githubSource.commit_sha ? ` · ${githubSource.commit_sha.slice(0, 8)}` : ''}`
    : health?.capabilities.github_public ? 'Submit a public GitHub repository' : health?.root || 'Connecting…'
  const publicMode = Boolean(githubSource || health?.capabilities.github_public)
  const tabCounts: Partial<Record<Tab, number>> = {
    findings: graph?.summary.findings,
    files: graph?.summary.files,
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">V</div>
          <div className="brand-copy">
            <p className="eyebrow">VINYAS</p>
            <h1>Architecture governance</h1>
            <p className="root-path" title={sourceLabel}>{sourceLabel}</p>
          </div>
        </div>
        <div className="topbar-tools">
          <span className="environment-badge">{publicMode ? 'Public GitHub analysis' : 'Local analysis'}</span>
          <div className="actions">
            {busy && <button className="button secondary" onClick={cancel} disabled={cancelRequested}>{cancelRequested ? 'Cancelling…' : 'Cancel'}</button>}
            {graph && <button className="button secondary" onClick={reset}>Analyze another</button>}
            {graph && <button className="button primary" onClick={() => githubSource ? void analyze() : void analyzeLocal()} disabled={busy}>Run again</button>}
          </div>
        </div>
      </header>

      {busy && <section className="progress-card" aria-live="polite"><div><strong>{job?.message}</strong><span>{job?.progress || 0}%</span></div><progress max="100" value={job?.progress || 0} /></section>}
      {job?.status === 'failed' && <div className="banner error"><strong>{job.error_code ? formatErrorCode(job.error_code) : 'Analysis failed'}</strong><span>{job.error || 'Analysis failed'}</span></div>}
      {job?.status === 'cancelled' && <div className="banner">Analysis cancelled. You can submit another repository.</div>}
      {error && <div className="banner error">{error}</div>}

      {graph ? <>
        <nav className="tabs" aria-label="Analysis views">
          {(['overview', 'findings', 'files', 'graph'] as Tab[]).map((item) => (
            <button key={item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>
              {item}
              {tabCounts[item] !== undefined ? <span className="tab-count">{tabCounts[item]}</span> : null}
            </button>
          ))}
        </nav>

        {tab === 'overview' && <main>
          <section className="metric-grid">
            <Metric label="Files" value={graph.summary.files} />
            <Metric label="Dependencies" value={graph.summary.dependencies} />
            <Metric label="Active findings" value={graph.summary.findings} tone={graph.summary.findings ? 'danger' : 'good'} />
            <Metric label="Cycles" value={graph.summary.cycles} tone={graph.summary.cycles ? 'danger' : 'good'} />
            <Metric label="Unresolved" value={graph.summary.unresolved} tone={graph.summary.unresolved ? 'warn' : 'good'} />
            <Metric label="Suppressed" value={graph.summary.suppressed} />
          </section>
          <section className="two-column">
            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">REQUIRES ATTENTION</p><h2>Top findings</h2></div><button className="text-button" onClick={() => setTab('findings')}>View all</button></div>
              <FindingList findings={findings.filter((item) => !item.suppressed).slice(0, 8)} onSelect={(item) => { setSelectedFinding(item); setTab('findings') }} />
            </article>
            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">EXPLAINABLE METRICS</p><h2>Dependency hotspots</h2></div><button className="text-button" onClick={() => setTab('files')}>View all</button></div>
              <FileTable files={files.slice(0, 8)} onSelect={(path) => { setSelectedFile(path); setTab('files') }} />
            </article>
          </section>
        </main>}

        {tab === 'findings' && <main className="workspace"><section className="panel grow"><div className="toolbar"><input aria-label="Filter findings" placeholder="Filter path, message, or evidence" value={query} onChange={(event) => setQuery(event.target.value)} /><select aria-label="Filter by rule" value={rule} onChange={(event) => setRule(event.target.value)}><option value="all">All rules</option>{rules.map((item) => <option key={item}>{item}</option>)}</select></div><FindingList findings={filteredFindings} onSelect={(item) => { setSelectedFinding(item); setExplanation(null) }} selected={selectedFinding?.fingerprint} /></section><EvidencePanel finding={selectedFinding} explanation={explanation} onExplain={async () => { if (!selectedFinding || !job) return; const result = await explainFinding(job.id, selectedFinding.fingerprint); setExplanation({ text: result.explanation, ai: result.ai_generated }) }} /></main>}
        {tab === 'files' && <main className="workspace"><section className="panel grow"><FileTable files={files} onSelect={setSelectedFile} selected={selectedFile} /></section><FilePanel file={selectedFileNode} edges={relatedEdges} /></main>}
        {tab === 'graph' && <main className="workspace"><section className="panel grow"><DependencyGraph files={files} edges={graph.edges} selected={selectedFile} onSelect={setSelectedFile} /></section><FilePanel file={selectedFileNode} edges={relatedEdges} /></main>}
      </> : !busy && <main className="welcome">
        <div className="welcome-icon">V</div>
        <p className="eyebrow">PUBLIC REPOSITORY ANALYSIS</p>
        <h2>{unavailable ? 'This analysis is no longer available.' : 'Trust the graph before acting on it.'}</h2>
        <p>{unavailable ? 'Temporary results can expire or be cleared when the free analysis service restarts.' : 'Enter a public GitHub repository URL to inspect dependencies, cycles, unresolved imports, governance violations, and evidence-backed metrics.'}</p>
        {unavailable && <button className="button secondary expired-action" onClick={reset}>Analyze another repository</button>}
        {!unavailable && health?.capabilities.github_public && <RepositoryForm
          value={repositoryUrl}
          error={formError}
          disabled={false}
          inputRef={repositoryInput}
          onChange={(value) => { setRepositoryUrl(value); setFormError('') }}
          onSubmit={analyze}
        />}
        {!unavailable && health?.capabilities.github_public && <p className="repository-note">Public GitHub repositories only · Default branch · Source removed after analysis</p>}
        {!unavailable && health && !health.capabilities.github_public && <button className="button primary" onClick={() => void analyzeLocal()}>Analyze local repository</button>}
      </main>}
    </div>
  )
}

function RepositoryForm({ value, error, disabled, inputRef, onChange, onSubmit }: { value: string; error: string; disabled: boolean; inputRef: React.RefObject<HTMLInputElement | null>; onChange: (value: string) => void; onSubmit: (event: React.FormEvent) => void }) {
  return <form className="repository-form" onSubmit={onSubmit} noValidate><label htmlFor="repository-url">GitHub repository URL</label><div className="repository-input-row"><input ref={inputRef} id="repository-url" type="url" inputMode="url" autoComplete="url" spellCheck={false} placeholder="https://github.com/owner/repository" value={value} onChange={(event) => onChange(event.target.value)} aria-describedby={error ? 'repository-error repository-help' : 'repository-help'} aria-invalid={Boolean(error)} disabled={disabled} /><button className="button primary" type="submit" disabled={disabled}>Analyze repository</button></div>{error && <p className="field-error" id="repository-error" role="alert">{error}</p>}<span className="sr-only" id="repository-help">Enter the root URL of a public GitHub repository.</span></form>
}

function errorMessage(cause: unknown, fallback: string) { return cause instanceof Error ? cause.message : fallback }

function formatErrorCode(value: string) { return value.split('_').map((part) => part[0].toUpperCase() + part.slice(1)).join(' ') }

function Metric({ label, value, tone = '' }: { label: string; value: number; tone?: string }) { return <article className={`metric ${tone}`}><span>{label}</span><strong>{value}</strong></article> }

function FindingList({ findings, onSelect, selected }: { findings: Finding[]; onSelect: (finding: Finding) => void; selected?: string }) {
  if (!findings.length) return <div className="empty-state">No matching active findings.</div>
  return <div className="finding-list">{findings.map((finding) => <button key={finding.fingerprint} className={`finding-row ${selected === finding.fingerprint ? 'selected' : ''}`} onClick={() => onSelect(finding)}><span className={`severity ${finding.severity}`}>{finding.severity}</span><span><strong>{finding.message}</strong><small>{finding.rule} · {finding.path || 'repository'}:{finding.line}</small></span></button>)}</div>
}

function EvidencePanel({ finding, explanation, onExplain }: { finding: Finding | null; explanation: { text: string; ai: boolean } | null; onExplain: () => void }) { return <aside className="panel inspector"><p className="eyebrow">FINDING EVIDENCE</p>{finding ? <><h2>{finding.rule}</h2><p>{finding.message}</p><dl><dt>Location</dt><dd><code>{finding.path || 'repository'}:{finding.line}</code></dd><dt>Severity</dt><dd>{finding.severity}</dd><dt>Source evidence</dt><dd><pre>{finding.evidence || 'Repository-level rule; no single source line.'}</pre></dd><dt>Fingerprint</dt><dd><code>{finding.fingerprint}</code></dd></dl><button className="button secondary explain" onClick={onExplain}>Explain verified finding</button>{explanation && <div className="explanation"><strong>{explanation.ai ? 'AI-generated explanation' : 'Deterministic explanation'}</strong><p>{explanation.text}</p></div>}</> : <p className="muted">Select a finding to see its source evidence and stable fingerprint.</p>}</aside> }

function FileTable({ files, onSelect, selected }: { files: FileNode[]; onSelect: (path: string) => void; selected?: string | null }) { return <div className="table-scroll"><table><thead><tr><th>File</th><th>Language</th><th>Fan-in</th><th>Fan-out</th><th>Symbols</th><th>Depth</th><th>Cycles</th></tr></thead><tbody>{files.map((file) => <tr key={file.path} className={selected === file.path ? 'selected' : ''} onClick={() => onSelect(file.path)}><td><code>{file.path}</code></td><td>{file.language}</td><td>{file.metrics.fan_in}</td><td>{file.metrics.fan_out}</td><td>{file.metrics.symbol_count}</td><td>{file.metrics.dependency_depth}</td><td>{file.metrics.cycle_participation}</td></tr>)}</tbody></table></div> }

function FilePanel({ file, edges }: { file: FileNode | null; edges: Graph['edges'] }) { return <aside className="panel inspector"><p className="eyebrow">FILE DETAILS</p>{file ? <><h2>{file.path}</h2><p className="muted">{file.language} · {file.symbols.length} symbols</p><dl><dt>Incoming / outgoing</dt><dd>{file.metrics.fan_in} / {file.metrics.fan_out}</dd><dt>Dependency depth</dt><dd>{file.metrics.dependency_depth}</dd><dt>Cycle participation</dt><dd>{file.metrics.cycle_participation}</dd></dl><h3>Connections</h3><ul className="connections">{edges.slice(0, 20).map((edge) => <li key={`${edge.source}:${edge.line}:${edge.target}`}><span>{edge.source === file.path ? 'OUT' : 'IN'}</span><code>{edge.source === file.path ? edge.target : edge.source}</code><small>{edge.evidence}</small></li>)}</ul></> : <p className="muted">Select a file from the table or graph to inspect incoming and outgoing dependencies.</p>}</aside> }

function App() {
  return window.location.pathname.startsWith('/app') ? <AnalyzerApp /> : <LandingPage />
}

export default App
