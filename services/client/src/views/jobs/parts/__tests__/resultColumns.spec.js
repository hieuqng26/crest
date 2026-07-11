import { describe, it, expect } from 'vitest'
import { columnsFromNames } from '../resultColumns.js'

describe('columnsFromNames', () => {
  it('marks numeric columns non-filterable so they do not fire distinct probes', () => {
    const cols = columnsFromNames(['sector', 'predicted', 'residual', 'actual'])
    const byField = Object.fromEntries(cols.map((c) => [c.field, c]))
    expect(byField.predicted.filterable).toBe(false)
    expect(byField.residual.filterable).toBe(false)
    expect(byField.actual.filterable).toBe(false)
    // categorical dimensions stay filterable (undefined ⇒ default true)
    expect(byField.sector.filterable).toBeUndefined()
  })
})
