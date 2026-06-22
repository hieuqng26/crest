import { describe, it, expect, beforeEach } from 'vitest'
import { getCookie } from '@/utils/cookies'

describe('getCookie', () => {
  beforeEach(() => { document.cookie = 'csrf_access_token=abc123; path=/' })
  it('reads a cookie value', () => { expect(getCookie('csrf_access_token')).toBe('abc123') })
  it('returns null for a missing cookie', () => { expect(getCookie('nope')).toBeNull() })
})
