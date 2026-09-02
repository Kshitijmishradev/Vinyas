import type { Finding, Graph, Job } from './types'

const API_BASE = import.meta.env.VITE_API_BASE || ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try { detail = (await response.json()).detail || detail } catch { /* non-JSON proxy error */ }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function serverHealth() {
  return request<{ root: string; version: string }>('/api/v1/health')
}

export async function startAnalysis() {
  return request<Job>('/api/v1/analyses', { method: 'POST', body: '{}' })
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
