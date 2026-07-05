<script setup>
import PageHeader from '@/components/ui/PageHeader.vue'

const ratings = ['AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'CCC', 'D']

const matrix = [
  [92.1,  5.2,  1.8,  0.6,  0.2,  0.1,  0.0,  0.0],
  [ 1.4, 89.3,  7.1,  1.6,  0.4,  0.1,  0.1,  0.0],
  [ 0.1,  2.3, 88.5,  7.2,  1.4,  0.3,  0.1,  0.1],
  [ 0.0,  0.2,  4.8, 83.1,  8.9,  2.1,  0.6,  0.3],
  [ 0.0,  0.1,  0.5,  6.1, 79.2,  9.8,  3.1,  1.2],
  [ 0.0,  0.0,  0.2,  0.8,  7.3, 74.8, 12.1,  4.8],
  [ 0.0,  0.0,  0.1,  0.3,  1.2,  8.9, 62.4, 27.1],
  [ 0.0,  0.0,  0.0,  0.0,  0.0,  0.0,  0.0,100.0]
]

// Diagonal (stable) = ink bg, yellow figures. Everything else = gray-intensity
// scaled by magnitude — flat monochrome, no red/green traffic-light coloring.
const cellStyle = (val, rowIdx, colIdx) => {
  if (rowIdx === colIdx) {
    return { background: 'var(--ink)', color: 'var(--yellow)' }
  }
  const alpha = Math.min(0.08 + val / 30 * 0.8, 0.85)
  return {
    background: `rgba(46, 46, 56, ${alpha.toFixed(2)})`,
    color: alpha > 0.45 ? '#FFFFFF' : 'var(--text-color)'
  }
}
</script>

<template>
  <div>
    <PageHeader eyebrow="ANALYSIS" title="Transitions" subtitle="1-year credit-grade transition probabilities (%). Ink diagonal = stable; gray intensity = migration size." />

    <div class="panel">
      <div class="matrix-grid matrix-grid--head">
        <div>FROM &#8594; TO</div>
        <div v-for="r in ratings" :key="r" class="ta-center">{{ r }}</div>
      </div>
      <div v-for="(row, ri) in matrix" :key="ri" class="matrix-grid matrix-grid--row">
        <div class="row-label">{{ ratings[ri] }}</div>
        <div
          v-for="(val, ci) in row" :key="ci"
          class="font-mono cell"
          :style="cellStyle(val, ri, ci)"
        >{{ val.toFixed(1) }}%</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 2px;
  padding: 16px;
}

.matrix-grid {
  display: grid;
  grid-template-columns: 90px repeat(8, 1fr);
  column-gap: 8px;
  align-items: center;
}
.matrix-grid--head {
  height: 36px;
  border-bottom: 2px solid var(--ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--text-color-muted);
}
.matrix-grid--row { padding: 2px 0; }
.ta-center { text-align: center; }
.row-label { font-size: 13px; font-weight: 600; }
.cell {
  margin: 2px 0;
  padding: 11px 0;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  border-radius: 2px;
}
</style>
