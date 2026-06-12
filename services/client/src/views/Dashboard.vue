<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const kpis = ref([
  { label: 'Total Runs',      value: 42,     icon: 'pi-play-circle',   color: 'text-blue-400' },
  { label: 'Successful',      value: 38,     icon: 'pi-check-circle',  color: 'text-green-400' },
  { label: 'Failed',          value: 4,      icon: 'pi-times-circle',  color: 'text-red-400' },
  { label: 'Datasets Loaded', value: 17,     icon: 'pi-database',      color: 'text-yellow-400' }
])

const recentRuns = ref([
  { run_id: 'a1b2c3d4', model: 'LogisticRegression', dataset: 'PD_2024_Q4.csv', status: 'success',  triggered_by: 'analyst@bank.com', finished_at: '2026-06-11 09:14' },
  { run_id: 'e5f6a7b8', model: 'ARIMA',               dataset: 'MacroFactors_Q3.parquet', status: 'success',  triggered_by: 'quant@bank.com',   finished_at: '2026-06-10 17:32' },
  { run_id: 'c9d0e1f2', model: 'GLM (Binomial)',       dataset: 'LGD_Corp_2023.xlsx',     status: 'failed',   triggered_by: 'analyst@bank.com', finished_at: '2026-06-10 11:05' },
  { run_id: 'b3c4d5e6', model: 'GradientBoosting',     dataset: 'PD_Retail_2024.csv',     status: 'running',  triggered_by: 'quant@bank.com',   finished_at: '—' },
  { run_id: 'f7a8b9c0', model: 'Ridge',                dataset: 'MacroFactors_Q2.parquet', status: 'success', triggered_by: 'risk@bank.com',    finished_at: '2026-06-09 14:21' }
])

const statusSeverity = (s) => ({ success: 'success', failed: 'danger', running: 'warning', queued: 'info' }[s] ?? 'secondary')

const goToRun = (run_id) => router.push({ name: 'calibrate_run', params: { run_id } })
const goToEval = (run_id) => router.push({ name: 'evaluate_run', params: { run_id } })
</script>

<template>
  <div class="p-4">
    <h2 class="text-2xl font-semibold mb-4">Dashboard</h2>

    <!-- KPI cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
      <div
        v-for="kpi in kpis"
        :key="kpi.label"
        class="surface-card border-round p-4 flex align-items-center gap-3 shadow-1"
      >
        <i :class="['pi text-3xl', kpi.icon, kpi.color]" />
        <div>
          <div class="text-3xl font-bold">{{ kpi.value }}</div>
          <div class="text-sm text-color-secondary">{{ kpi.label }}</div>
        </div>
      </div>
    </div>

    <!-- Recent runs -->
    <div class="surface-card border-round shadow-1 p-4">
      <h3 class="text-lg font-semibold mb-3">Recent Calibration Runs</h3>
      <DataTable :value="recentRuns" :rows="5" stripedRows size="small" class="w-full">
        <Column field="run_id"       header="Run ID"     style="width:10rem">
          <template #body="{ data }">
            <span class="font-mono text-xs">{{ data.run_id }}</span>
          </template>
        </Column>
        <Column field="model"        header="Model"       />
        <Column field="dataset"      header="Dataset"     />
        <Column field="triggered_by" header="Triggered By" />
        <Column field="finished_at"  header="Finished"    />
        <Column field="status"       header="Status">
          <template #body="{ data }">
            <Tag :value="data.status" :severity="statusSeverity(data.status)" />
          </template>
        </Column>
        <Column header="Actions" style="width:8rem">
          <template #body="{ data }">
            <div class="flex gap-2">
              <Button icon="pi pi-eye"        text size="small" @click="goToRun(data.run_id)"  v-tooltip="'Progress'" />
              <Button icon="pi pi-chart-bar"  text size="small" @click="goToEval(data.run_id)" v-tooltip="'Evaluate'" :disabled="data.status !== 'success'" />
            </div>
          </template>
        </Column>
      </DataTable>
    </div>
  </div>
</template>
