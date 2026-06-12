export const intersectColumns = (a, b) =>
  (a || []).filter(c => (b || []).includes(c))

export const findUnjoinable = (datasets, steps) => {
  const bad = []
  for (let i = 0; i < steps.length; i++) {
    if (steps[i].type === 'union') continue
    const overlap = intersectColumns(datasets[i].columns, datasets[i + 1].columns)
    if (overlap.length === 0) bad.push(i)
    else if (!steps[i].on || steps[i].on.length === 0) bad.push(i)
  }
  return bad
}

export const projectSchema = (datasets, steps) => {
  if (!datasets.length) return { columns: [], estimatedRows: 0 }
  if (datasets.length === 1) {
    return { columns: datasets[0].columns.slice(), estimatedRows: datasets[0].row_count }
  }

  let accCols = datasets[0].columns.slice()
  let accRows = datasets[0].row_count

  for (let i = 0; i < steps.length; i++) {
    const right = datasets[i + 1]
    const step = steps[i]

    if (step.type === 'union') {
      accCols = accCols.filter(c => right.columns.includes(c))
      accRows = accRows + right.row_count
      continue
    }

    const joinKeys = new Set(step.on || [])
    const newCols = []
    const seen = new Set()
    const rightOverlap = new Set(accCols.filter(c => right.columns.includes(c)))

    for (const c of accCols) {
      if (joinKeys.has(c)) {
        if (!seen.has(c)) { newCols.push(c); seen.add(c) }
      } else if (rightOverlap.has(c)) {
        const k = `${c}_x`; if (!seen.has(k)) { newCols.push(k); seen.add(k) }
      } else {
        if (!seen.has(c)) { newCols.push(c); seen.add(c) }
      }
    }
    for (const c of right.columns) {
      if (joinKeys.has(c)) continue
      if (rightOverlap.has(c)) {
        const k = `${c}_y`; if (!seen.has(k)) { newCols.push(k); seen.add(k) }
      } else {
        if (!seen.has(c)) { newCols.push(c); seen.add(c) }
      }
    }

    accCols = newCols
    switch (step.type) {
      case 'inner': accRows = Math.min(accRows, right.row_count); break
      case 'left':  accRows = accRows; break
      case 'outer': accRows = Math.max(accRows, right.row_count); break
      default:      accRows = Math.min(accRows, right.row_count)
    }
  }

  return { columns: accCols, estimatedRows: accRows }
}
