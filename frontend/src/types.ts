export type Summary = {
  files: number
  dependencies: number
  findings: number
  suppressed: number
  cycles: number
  unresolved: number
  external: number
}

export type Finding = {
  fingerprint: string
  rule: string
  severity: 'error' | 'warning'
  message: string
  path: string
  line: number
  evidence: string
  suppressed: boolean
  suppression_reason: string
}

export type Metrics = {
  fan_in: number
  fan_out: number
  symbol_count: number
  dependency_depth: number
  cycle_participation: number
}

export type FileNode = {
  path: string
  language: string
  content_hash: string
  symbols: Array<{ name: string; kind: string; line: number }>
  metrics: Metrics
}

export type Edge = {
  source: string
  target: string
  line: number
  evidence: string
  resolution: string
  confidence: string
}

export type Graph = {
  analysis_id: string
  root: string
  files: FileNode[]
  edges: Edge[]
  cycles: string[][]
  summary: Summary
}

export type Job = {
  id: string
  root: string
  status: 'queued' | 'running' | 'complete' | 'failed' | 'cancelled'
  progress: number
  message: string
  error?: string
  summary?: Summary
}
