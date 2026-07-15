import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import WorkflowStepper from '../WorkflowStepper.vue'

// Build a `wf` object shaped like the WorkflowDetail payload.
const wf = ({ status, stage, cal, fc, analysis, skipped }) => ({
  status,
  current_stage: stage,
  analysis_skipped_reason: skipped ?? null,
  analysis: analysis ?? null,
  targets: [
    { target_col: 'gdp', calibration: { status: cal }, forecast: fc ? { status: fc } : null }
  ]
})

// Returns the state class (is-*) of each of the 4 step <li>s.
const states = (wrapper) =>
  wrapper.findAll('.wf-step').map((li) => {
    const m = [...li.classes()].find((c) => c.startsWith('is-'))
    return m.replace('is-', '')
  })

describe('WorkflowStepper', () => {
  it('shows all steps pending/queued at the start', () => {
    const w = mount(WorkflowStepper, {
      props: { wf: wf({ status: 'queued', stage: 'training', cal: 'queued' }) }
    })
    expect(states(w)).toEqual(['queued', 'pending', 'pending', 'pending'])
  })

  it('marks training running while calibration runs', () => {
    const w = mount(WorkflowStepper, {
      props: { wf: wf({ status: 'running', stage: 'training', cal: 'running' }) }
    })
    expect(states(w)).toEqual(['running', 'pending', 'pending', 'pending'])
  })

  it('advances to forecast once training succeeds', () => {
    const w = mount(WorkflowStepper, {
      props: { wf: wf({ status: 'running', stage: 'forecast', cal: 'success', fc: 'running' }) }
    })
    expect(states(w)).toEqual(['success', 'running', 'pending', 'pending'])
  })

  it('runs credit analysis after forecasts succeed and shows the compute percentage', () => {
    // Client-compute band is 0→80 of the credit run's progress, mapped to 0–100%.
    const w = mount(WorkflowStepper, {
      props: {
        wf: wf({
          status: 'running', stage: 'analysis', cal: 'success', fc: 'success',
          analysis: { status: 'running', progress: 40 }
        })
      }
    })
    expect(states(w)).toEqual(['success', 'success', 'running', 'pending'])
    expect(w.text()).toContain('50%') // 40 / 80 → 50%
  })

  it('moves to the Complete step with a materialisation percentage once compute finishes', () => {
    // Past the compute band (progress ≥ 80) the run is still `running`, now
    // materialising analysis views — Credit reads done, Complete shows its own %.
    const w = mount(WorkflowStepper, {
      props: {
        wf: wf({
          status: 'running', stage: 'analysis', cal: 'success', fc: 'success',
          analysis: { status: 'running', progress: 90 }
        })
      }
    })
    expect(states(w)).toEqual(['success', 'success', 'success', 'running'])
    expect(w.text()).toContain('50%') // (90 − 80) / 20 → 50%
  })

  it('keeps the Complete step running in the window after credit success but before workflow done', () => {
    // Credit run reached success (materialisation finished) but advance_workflow
    // has not yet flipped the workflow to done — Complete stays running.
    const w = mount(WorkflowStepper, {
      props: {
        wf: wf({
          status: 'running', stage: 'analysis', cal: 'success', fc: 'success',
          analysis: { status: 'success', progress: 100 }
        })
      }
    })
    expect(states(w)).toEqual(['success', 'success', 'success', 'running'])
  })

  it('falls back to a Finalizing label when materialisation progress is not yet available', () => {
    // Credit compute just crossed into materialisation but the light poll hasn't
    // carried a progress value into the object yet (progress defaults to 0).
    const w = mount(WorkflowStepper, {
      props: {
        wf: wf({
          status: 'running', stage: 'analysis', cal: 'success', fc: 'success',
          analysis: { status: 'success' }
        })
      }
    })
    expect(states(w)).toEqual(['success', 'success', 'success', 'running'])
    expect(w.text()).toContain('Finalizing')
  })

  it('completes the final step when credit analysis succeeds', () => {
    const w = mount(WorkflowStepper, {
      props: {
        wf: wf({
          status: 'success', stage: 'done', cal: 'success', fc: 'success',
          analysis: { status: 'success' }
        })
      }
    })
    expect(states(w)).toEqual(['success', 'success', 'success', 'success'])
  })

  it('skips credit analysis but still completes', () => {
    const w = mount(WorkflowStepper, {
      props: {
        wf: wf({
          status: 'success', stage: 'done', cal: 'success', fc: 'success',
          skipped: 'Credit analysis skipped — no credit portfolio dataset available'
        })
      }
    })
    expect(states(w)).toEqual(['success', 'success', 'skipped', 'success'])
  })

  it('infers skipped credit analysis when the workflow finished without an analysis run', () => {
    // Light-polled object may reach done/success before the skip reason is
    // re-fetched; a finished workflow with no analysis run means it was skipped.
    const w = mount(WorkflowStepper, {
      props: {
        wf: wf({ status: 'success', stage: 'done', cal: 'success', fc: 'success' })
      }
    })
    expect(states(w)).toEqual(['success', 'success', 'skipped', 'success'])
  })

  it('surfaces a training failure on the training step', () => {
    const w = mount(WorkflowStepper, {
      props: { wf: wf({ status: 'failed', stage: 'training', cal: 'failed' }) }
    })
    expect(states(w)).toEqual(['failed', 'pending', 'pending', 'pending'])
  })

  it('surfaces a credit-analysis failure on the credit step', () => {
    const w = mount(WorkflowStepper, {
      props: {
        wf: wf({
          status: 'failed', stage: 'analysis', cal: 'success', fc: 'success',
          analysis: { status: 'failed' }
        })
      }
    })
    expect(states(w)).toEqual(['success', 'success', 'failed', 'pending'])
  })
})
