<script setup>
import { ref, computed } from 'vue'

const portfolio = ref('Corporate')
const portfolioOptions = ['Corporate', 'Retail', 'SME']

const kpis = [
  { label: 'Total ECL',       value: 'USD 153.6M', delta: '+2.3%', deltaTone: 'down', sub: 'vs prev. quarter' },
  { label: 'Total EAD',       value: '6.88B',      delta: '+1.1%', deltaTone: 'up',   sub: 'across all stages' },
  { label: 'Coverage ratio',  value: '2.23%',      delta: '+0.04 pp', deltaTone: 'down', sub: 'ECL / EAD' }
]

const stageData = computed(() => ({
  labels: ['Stage 1', 'Stage 2', 'Stage 3'],
  datasets: [{
    data: [12.4, 28.7, 58.9],
    backgroundColor: ['#34d399', '#facc15', '#f87171'],
    borderWidth: 0,
    hoverOffset: 6
  }]
}))

const stageLegend = [
  { label: 'Stage 1', sub: '12-month ECL',  color: '#34d399', value: '12.4M' },
  { label: 'Stage 2', sub: 'Lifetime ECL',  color: '#facc15', value: '28.7M' },
  { label: 'Stage 3', sub: 'Lifetime ECL · credit-impaired', color: '#f87171', value: '58.9M' }
]

const trend = {
  labels: ['2022-Q1','2022-Q2','2022-Q3','2022-Q4','2023-Q1','2023-Q2','2023-Q3','2023-Q4','2024-Q1','2024-Q2'],
  datasets: [{
    label: 'ECL (USD M)',
    data: [142, 138, 151, 163, 158, 171, 165, 178, 182, 191],
    borderColor: '#60a5fa',
    backgroundColor: 'rgba(96,165,250,0.08)',
    borderWidth: 2,
    fill: true,
    tension: 0.35,
    pointRadius: 0,
    pointHoverRadius: 5
  }]
}

const eclTable = ref([
  { segment: 'Large Corporate', ead: '2,140M', pd: '1.2%', lgd: '42%', ecl: '10.8M', stage: 1 },
  { segment: 'Mid-Market',      ead: '890M',   pd: '2.8%', lgd: '48%', ecl: '12.0M', stage: 2 },
  { segment: 'SME',             ead: '430M',   pd: '4.1%', lgd: '55%', ecl: '9.7M',  stage: 2 },
  { segment: 'Retail Mortgage', ead: '3,200M', pd: '0.9%', lgd: '35%', ecl: '10.1M', stage: 1 },
  { segment: 'Non-Performing',  ead: '220M',   pd: '78%',  lgd: '65%', ecl: '111M',  stage: 3 }
])

const STAGE_COLOR = { 1: '#34d399', 2: '#facc15', 3: '#f87171' }
const stageDot   = (s) => STAGE_COLOR[s] || 'var(--surface-400)'

const lineOptions = {
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
  interaction: { mode: 'nearest', axis: 'x', intersect: false },
  scales: {
    x: { ticks: { color: '#9ca3af', font: { size: 10 } }, grid: { display: false } },
    y: { ticks: { color: '#9ca3af', font: { size: 10 } }, grid: { color: 'rgba(156,163,175,0.08)' }, border: { display: false } }
  }
}
const doughnutOptions = {
  maintainAspectRatio: false,
  cutout: '70%',
  plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.parsed}M` } } }
}
</script>

<template>
  <div class="p-5 mx-auto" style="max-width: 1400px">
    <!-- Header -->
    <header class="flex align-items-end justify-content-between mb-5 flex-wrap gap-3">
      <div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">IFRS 9 ECL</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">Expected credit losses by stage and segment.</p>
      </div>
      <div class="seg-pills">
        <button
          v-for="p in portfolioOptions"
          :key="p"
          type="button"
          class="seg-pill"
          :class="{ 'is-active': portfolio === p }"
          @click="portfolio = p"
        >{{ p }}</button>
      </div>
    </header>

    <!-- KPI strip -->
    <div class="stat-strip mb-5">
      <div v-for="k in kpis" :key="k.label" class="stat-cell">
        <div class="text-color-secondary text-xs uppercase tracking-wide mb-1">{{ k.label }}</div>
        <div class="flex align-items-baseline gap-2">
          <span class="text-2xl font-semibold tracking-tight">{{ k.value }}</span>
          <span class="text-xs" :class="k.deltaTone === 'up' ? 'text-green-400' : 'text-red-400'">
            <i :class="k.deltaTone === 'up' ? 'pi pi-arrow-up' : 'pi pi-arrow-down'" class="text-xs" />
            {{ k.delta }}
          </span>
        </div>
        <div class="text-xs text-color-secondary mt-1">{{ k.sub }}</div>
      </div>
    </div>

    <!-- Charts row -->
    <div class="grid m-0 gap-4 mb-4 grid-cols-1 lg:grid-cols-2">
      <!-- Stage breakdown -->
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">ECL by IFRS 9 stage</span>
        </div>
        <div class="grid m-0 align-items-center" style="grid-template-columns: 180px 1fr">
          <div style="height: 180px">
            <Chart type="doughnut" :data="stageData" :options="doughnutOptions" class="h-full" />
          </div>
          <div class="flex flex-column gap-3">
            <div v-for="s in stageLegend" :key="s.label" class="flex align-items-center gap-3">
              <span class="legend-dot" :style="{ background: s.color }" />
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium">{{ s.label }}</div>
                <div class="text-xs text-color-secondary">{{ s.sub }}</div>
              </div>
              <div class="text-sm font-mono">{{ s.value }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Trend -->
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">ECL trend</span>
          <span class="text-xs text-color-secondary">Last 10 quarters · USD M</span>
        </div>
        <div style="height: 220px">
          <Chart type="line" :data="trend" :options="lineOptions" class="h-full" />
        </div>
      </div>
    </div>

    <!-- Segment breakdown table -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">Segment breakdown</span>
        <span class="text-xs text-color-secondary">{{ eclTable.length }} segments</span>
      </div>
      <div class="bare-table">
        <DataTable :value="eclTable" size="small" class="bare-table-inner">
          <Column field="segment" header="Segment" />
          <Column field="ead"     header="EAD" />
          <Column field="pd"      header="PD" />
          <Column field="lgd"     header="LGD" />
          <Column field="ecl"     header="ECL" />
          <Column header="Stage" style="width: 8rem">
            <template #body="{ data }">
              <div class="flex align-items-center gap-2">
                <span class="legend-dot" :style="{ background: stageDot(data.stage) }" />
                <span class="text-sm">Stage {{ data.stage }}</span>
              </div>
            </template>
          </Column>
        </DataTable>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Segmented pills (matches Jobs / Run pages) */
.seg-pills {
  display: inline-flex;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  padding: 4px;
  gap: 2px;
}
.seg-pill {
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  border: 0;
  background: transparent;
  border-radius: 8px;
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}
.seg-pill:hover { color: var(--text-color); }
.seg-pill.is-active {
  background: var(--surface-100, var(--surface-ground));
  color: var(--text-color);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}

/* Flat KPI strip */
.stat-strip {
  display: flex;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  overflow: hidden;
}
.stat-cell {
  flex: 1;
  padding: 1rem 1.25rem;
}
.stat-cell + .stat-cell {
  border-left: 1px solid var(--surface-border);
}

/* Panel — flat card replacement */
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.25rem 1.25rem 1rem;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.panel-title {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--text-color-secondary);
}

/* Dot used for stage / legend */
.legend-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}

/* Flat table */
.bare-table { margin: 0 -1.25rem -1rem; }
:deep(.bare-table-inner .p-datatable-thead > tr > th) {
  background: transparent;
  color: var(--text-color-secondary);
  font-weight: 500;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.6rem 1.25rem;
}
:deep(.bare-table-inner .p-datatable-tbody > tr > td) {
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.85rem 1.25rem;
  font-size: 0.875rem;
}
:deep(.bare-table-inner .p-datatable-tbody > tr:last-child > td) {
  border-bottom: 0;
}
</style>
