<script setup>
import { ref } from 'vue'

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

const cellColor = (val, rowIdx, colIdx) => {
  if (rowIdx === colIdx) return 'rgba(96,165,250,0.35)'
  if (colIdx === ratings.length - 1 && rowIdx !== ratings.length - 1) {
    if (val > 10) return 'rgba(248,113,113,0.6)'
    if (val > 2)  return 'rgba(251,191,36,0.4)'
    return 'rgba(248,113,113,0.15)'
  }
  if (colIdx > rowIdx) return `rgba(248,113,113,${Math.min(val / 30, 0.7)})`
  return `rgba(52,211,153,${Math.min(val / 30, 0.5)})`
}
</script>

<template>
  <div class="p-4">
    <h2 class="text-2xl font-semibold mb-1">Credit Grade Transition Matrix</h2>
    <p class="text-color-secondary text-sm mb-4">1-year transition probabilities (%). Blue = diagonal (stable), green = upgrade, red = downgrade.</p>

    <div class="surface-card border-round shadow-1 p-4 overflow-x-auto">
      <table class="w-full text-center text-sm" style="border-collapse:separate; border-spacing:2px">
        <thead>
          <tr>
            <th class="text-color-secondary text-xs px-2 py-2 text-left">From \ To</th>
            <th v-for="r in ratings" :key="r" class="text-color-secondary text-xs px-2 py-2">{{ r }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ri) in matrix" :key="ri">
            <td class="text-color-secondary text-xs font-medium px-2 py-2 text-left">{{ ratings[ri] }}</td>
            <td
              v-for="(val, ci) in row"
              :key="ci"
              class="border-round px-2 py-2 font-mono text-xs font-semibold"
              :style="{ backgroundColor: cellColor(val, ri, ci), minWidth: '52px' }"
            >
              {{ val.toFixed(1) }}%
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
