import { describe, it, expect } from 'vitest'
import { can } from '@/utils/permissions'

describe('can', () => {
  it('grants only explicitly-held permissions', () => {
    const p = ['dataset:read', 'model_config:read', 'credit_risk:read']
    expect(can(p, 'dataset:read')).toBe(true)
    expect(can(p, 'dataset:write')).toBe(false)
    expect(can(p, 'user:read')).toBe(false)
  })
  it('analyst can execute runs it holds', () => {
    expect(can(['credit_risk:read', 'credit_risk:execute'], 'credit_risk:execute')).toBe(true)
  })
  it('superuser wildcard allows everything', () => {
    expect(can(['*'], 'user:write')).toBe(true)
    expect(can(['*'], 'role:write')).toBe(true)
  })
  it('empty permissions deny', () => {
    expect(can([], 'dataset:read')).toBe(false)
    expect(can(null, 'dataset:read')).toBe(false)
  })
})
