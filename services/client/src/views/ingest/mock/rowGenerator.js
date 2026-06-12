const mulberry32 = (a) => {
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const SECTORS  = ['Manufacturing', 'Retail', 'Finance', 'Energy', 'Healthcare', 'Tech', 'RealEstate', 'Transport']
const RATINGS  = ['AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'CCC', 'D']
const REGIONS  = ['APAC', 'EMEA', 'AMER', 'LATAM']
const PRODUCTS = ['Mortgage', 'CreditCard', 'AutoLoan', 'PersonalLoan', 'BizLoan']
const COLLAT   = ['RealEstate', 'Cash', 'Equipment', 'Inventory', 'None']
const SENIOR   = ['Senior', 'Subordinated', 'Junior']

const cellFor = (col, rng, absIdx) => {
  switch (col) {
    case 'obligor_id':      return `OB${String(absIdx).padStart(7, '0')}`
    case 'customer_id':     return `C${String(absIdx).padStart(8, '0')}`
    case 'facility_id':     return `F${String(absIdx).padStart(7, '0')}`
    case 'default_flag':    return rng() < 0.08 ? 1 : 0
    case 'pd_estimate':     return +(rng() * 0.15).toFixed(4)
    case 'lgd':             return +(0.25 + rng() * 0.5).toFixed(3)
    case 'ead':             return Math.round(50_000 + rng() * 5_000_000)
    case 'recovery_rate':   return +(0.3 + rng() * 0.5).toFixed(3)
    case 'rating':          return RATINGS[Math.floor(rng() * RATINGS.length)]
    case 'sector':          return SECTORS[Math.floor(rng() * SECTORS.length)]
    case 'region':          return REGIONS[Math.floor(rng() * REGIONS.length)]
    case 'product':         return PRODUCTS[Math.floor(rng() * PRODUCTS.length)]
    case 'collateral_type': return COLLAT[Math.floor(rng() * COLLAT.length)]
    case 'seniority':       return SENIOR[Math.floor(rng() * SENIOR.length)]
    case 'tenure_months':   return Math.floor(rng() * 360)
    case 'year':            return 2018 + Math.floor(rng() * 8)
    case 'period':          return `${2018 + Math.floor(absIdx / 4)}-Q${(absIdx % 4) + 1}`
    case 'gdp_growth':      return +((rng() - 0.3) * 8).toFixed(2)
    case 'unemployment':    return +(3 + rng() * 9).toFixed(2)
    case 'inflation':       return +(rng() * 7).toFixed(2)
    case 'policy_rate':     return +(rng() * 6).toFixed(2)
    case 'fx_usd':          return +(0.8 + rng() * 0.8).toFixed(4)
    default:                return `val_${absIdx}_${col}`
  }
}

export const generateRows = ({ datasetId, columns, offset, limit, totalRows }) => {
  const end = Math.min(offset + limit, totalRows)
  const out = []
  for (let i = offset; i < end; i++) {
    const rng = mulberry32(datasetId * 1_000_003 + i)
    const row = { __idx: i + 1 }
    for (const col of columns) row[col] = cellFor(col, rng, i + 1)
    out.push(row)
  }
  return out
}

export const sortRows = (rows, field, order) => {
  if (!field || !order) return rows
  const dir = order === 1 ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = a[field], vb = b[field]
    if (va === vb) return 0
    if (va === null || va === undefined) return 1
    if (vb === null || vb === undefined) return -1
    return va > vb ? dir : -dir
  })
}
