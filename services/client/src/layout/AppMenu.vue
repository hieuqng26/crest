<script setup>
import { ref, onMounted } from 'vue'
import AppMenuItem from './AppMenuItem.vue'

const model = [
  {
    label: 'Data',
    items: [
      { label: 'Datasets', to: { name: 'datasets' }, module: 'ingest' }
    ]
  },
  {
    label: 'Models',
    items: [
      { label: 'Model Catalog',          to: { name: 'models' },         module: 'configure' },
      { label: 'Model Configurations',   to: { name: 'configurations' }, module: 'configure' },
      { label: 'New Calibration',        to: { name: 'calibrate_new' },  module: 'calibrate' },
      { label: 'Calibration Jobs',       to: { name: 'calibrate_jobs' }, module: 'calibrate' }
    ]
  },
  {
    label: 'Forecast',
    items: [
      { label: 'New Forecast',   to: { name: 'forecast_new' },  module: 'forecast' },
      { label: 'Forecast Jobs',  to: { name: 'forecast_jobs' }, module: 'forecast' }
    ]
  },
  {
    label: 'Credit Risk',
    items: [
      { label: 'New Analysis',  to: { name: 'credit_risk_new' },         module: 'credit_risk' },
      { label: 'Analysis Jobs', to: { name: 'credit_risk_jobs' },        module: 'credit_risk' },
      { label: 'IFRS 9 ECL',   to: { name: 'credit_risk_ecl' },         module: 'credit_risk' },
      { label: 'PD / LGD',     to: { name: 'credit_risk_pd_lgd' },      module: 'credit_risk' },
      { label: 'Transitions',  to: { name: 'credit_risk_transitions' },  module: 'credit_risk' }
    ]
  },
  {
    label: 'System',
    items: [
      { label: 'User Access Management', to: { name: 'uam' }, module: 'uam' },
      { label: 'Audit Logs',             to: { name: 'log' }, module: 'log', submodule_for_role: 'auditlog' }
    ]
  }
]

const filteredModel = ref([])
onMounted(() => { filteredModel.value = model })
</script>

<template>
  <ul class="layout-menu">
    <template v-for="(item, i) in filteredModel" :key="item">
      <app-menu-item v-if="!item.separator" :item="item" :index="i" />
      <li v-if="item.separator" class="menu-separator" />
    </template>
  </ul>
</template>

<style lang="scss" scoped></style>
