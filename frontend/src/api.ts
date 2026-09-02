import type { Finding, Graph, Health, Job } from './types'

const API_BASE = import.meta.env.VITE_API_BASE || ''

export class ApiError extends Error {
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    let code: string | undefined
    try {
      const payload = await response.json() as { detail?: string | { code?: string; message?: string } }
      if (typeof payload.detail === 'string') detail = payload.detail
      else if (payload.detail) {
        detail = payload.detail.message || detail
        code = payload.detail.code
      }
    } catch { /* non-JSON proxy error */ }
    throw new ApiError(detail, response.status, code)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function serverHealth() {
  return request<Health>('/api/v1/health')
}

export async function startAnalysis(repositoryUrl: string) {
  return request<Job>('/api/v1/analyses', {
    method: 'POST',
    body: JSON.stringify({ repository_url: repositoryUrl }),
  })
}

export async function startLocalAnalysis() {
  return request<Job>('/api/v1/analyses', { method: 'POST', body: '{}' })
}

export function normalizeGitHubRepositoryUrl(value: string) {
  const raw = value.trim()
  let parsed: URL
  try { parsed = new URL(raw) } catch { throw new Error('Enter a valid GitHub repository URL.') }
  const authority = raw.slice('https://'.length).split('/', 1)[0]
  if (
    parsed.protocol !== 'https:' || parsed.hostname.toLowerCase() !== 'github.com' ||
    authority.toLowerCase() !== 'github.com' || parsed.username || parsed.password || parsed.port || parsed.search || parsed.hash ||
    parsed.pathname.includes('%')
  ) throw new Error('Use https://github.com/owner/repository.')
  const parts = parsed.pathname.split('/').filter(Boolean)
  if (parts.length !== 2) throw new Error('Use a repository URL without a branch or file path.')
  const owner = parts[0]
  const repository = parts[1].endsWith('.git') ? parts[1].slice(0, -4) : parts[1]
  const valid = /^[A-Za-z0-9_.-]+$/
  if (!owner || !repository || !valid.test(owner) || !valid.test(repository) || ['.', '..'].includes(owner) || ['.', '..'].includes(repository)) {
    throw new Error('Enter a valid GitHub owner and repository name.')
  }
  return `https://github.com/${owner}/${repository}`
}

export async function analysisStatus(id: string) {
  return request<Job>(`/api/v1/analyses/${id}`)
}

export async function analysisResults(id: string) {
  const [graphResponse, findingResponse] = await Promise.all([
    request<Graph>(`/api/v1/analyses/${id}/graph`),
    request<{ findings: Finding[] }>(`/api/v1/analyses/${id}/findings`),
  ])
  return { graph: graphResponse, findings: findingResponse.findings }
}

export async function cancelAnalysis(id: string) {
  await request<void>(`/api/v1/analyses/${id}`, { method: 'DELETE' })
}

export async function explainFinding(id: string, fingerprint: string) {
  return request<{ explanation: string; ai_generated: boolean }>(
    `/api/v1/analyses/${id}/explanations`,
    { method: 'POST', body: JSON.stringify({ finding_fingerprint: fingerprint }) },
  )
}
