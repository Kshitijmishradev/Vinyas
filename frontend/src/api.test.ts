import { describe, expect, it } from 'vitest'
import { normalizeGitHubRepositoryUrl } from './api'

describe('normalizeGitHubRepositoryUrl', () => {
  it('normalizes a public repository root URL', () => {
    expect(normalizeGitHubRepositoryUrl(' https://github.com/Acme/demo.git/ '))
      .toBe('https://github.com/Acme/demo')
  })

  it.each([
    'http://github.com/acme/demo',
    'https://evil.example/acme/demo',
    'https://user:secret@github.com/acme/demo',
    'https://github.com:443/acme/demo',
    'https://github.com/acme/demo/tree/main',
    'https://github.com/acme/demo?tab=readme',
    'https://github.com/acme/%2e%2e',
  ])('rejects unsafe or unsupported URL %s', (value) => {
    expect(() => normalizeGitHubRepositoryUrl(value)).toThrow()
  })
})
