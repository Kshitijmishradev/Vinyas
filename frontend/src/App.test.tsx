import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ApiError } from './api'
import type { Health, Job } from './types'

const mocks = vi.hoisted(() => ({
  serverHealth: vi.fn(),
  startAnalysis: vi.fn(),
  startLocalAnalysis: vi.fn(),
  analysisStatus: vi.fn(),
  analysisResults: vi.fn(),
  cancelAnalysis: vi.fn(),
  explainFinding: vi.fn(),
}))

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, ...mocks }
})

const health: Health = {
  status: 'ok',
  root: '/app',
  version: '1.1.0',
  capabilities: { local: true, github_public: true },
}

const queuedJob: Job = {
  id: 'job-123',
  root: 'https://github.com/acme/demo',
  status: 'queued',
  progress: 0,
  message: 'Queued',
  source: {
    kind: 'github',
    repository_url: 'https://github.com/acme/demo',
    owner: 'acme',
    repository: 'demo',
    ref: 'HEAD',
    commit_sha: null,
  },
}

describe('public repository analyzer', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/app')
    mocks.serverHealth.mockResolvedValue(health)
    mocks.startAnalysis.mockResolvedValue(queuedJob)
    mocks.analysisStatus.mockReset()
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('validates and submits a canonical GitHub repository URL', async () => {
    render(<App />)
    const input = await screen.findByRole('textbox', { name: 'GitHub repository URL' })
    const submit = screen.getByRole('button', { name: 'Analyze repository' })
    await waitFor(() => expect(submit).toBeEnabled())
    fireEvent.change(input, { target: { value: 'https://github.com/acme/demo.git/' } })
    fireEvent.click(submit)

    await waitFor(() => expect(mocks.startAnalysis).toHaveBeenCalledWith('https://github.com/acme/demo'))
    expect(window.location.search).toBe('?analysis=job-123')
    expect(await screen.findByText('Queued')).toBeInTheDocument()
  })

  it('shows inline validation without creating a job', async () => {
    render(<App />)
    const input = await screen.findByRole('textbox', { name: 'GitHub repository URL' })
    fireEvent.change(input, { target: { value: 'https://evil.example/acme/demo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze repository' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('github.com/owner/repository')
    expect(mocks.startAnalysis).not.toHaveBeenCalled()
  })

  it('shows a recovery state for an expired result link', async () => {
    window.history.replaceState(null, '', '/app?analysis=expired-id')
    mocks.analysisStatus.mockRejectedValue(new ApiError('analysis has expired', 410))
    render(<App />)

    expect(await screen.findByText('This analysis is no longer available.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze another repository' })).toBeInTheDocument()
  })

  it('surfaces a server capacity error without changing the URL', async () => {
    mocks.startAnalysis.mockRejectedValueOnce(
      new ApiError('The public analyzer is at capacity. Try again shortly.', 429),
    )
    render(<App />)
    const input = await screen.findByRole('textbox', { name: 'GitHub repository URL' })
    fireEvent.change(input, { target: { value: 'https://github.com/acme/demo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze repository' }))

    expect(await screen.findByText('The public analyzer is at capacity. Try again shortly.')).toBeInTheDocument()
    expect(window.location.search).toBe('')
  })

  it('requests cancellation for a queued analysis', async () => {
    render(<App />)
    const input = await screen.findByRole('textbox', { name: 'GitHub repository URL' })
    fireEvent.change(input, { target: { value: 'https://github.com/acme/demo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze repository' }))

    const cancel = await screen.findByRole('button', { name: 'Cancel' })
    fireEvent.click(cancel)

    await waitFor(() => expect(mocks.cancelAnalysis).toHaveBeenCalledWith('job-123'))
    expect(screen.getByRole('button', { name: 'Cancelling…' })).toBeDisabled()
  })
})
