<script setup>
import { computed } from 'vue'
import { useStore } from 'vuex'
import AppMenuItem from './AppMenuItem.vue'

const store = useStore()
const can = (p) => store.getters.can(p)

const model = [
  {
    label: 'Data',
    items: [
      { label: 'Datasets', to: { name: 'datasets' }, module: 'ingest', perm: 'dataset:read' }
    ]
  },
  {
    label: 'Models',
    items: [
      { label: 'Model Catalog',          to: { name: 'models' },               module: 'configure', perm: 'model_config:read' },
      { label: 'Model Configurations',   to: { name: 'configurations' },       module: 'configure', perm: 'model_config:read' },
      { label: 'New Calibration',        to: { name: 'calibrate_new' },        module: 'calibrate', perm: 'calibration:read' },
      { label: 'Calibration Jobs',       to: { name: 'calibrate_jobs' },       module: 'calibrate', perm: 'calibration:read' }
    ]
  },
  {
    label: 'Forecast',
    items: [
      { label: 'New Forecast',  to: { name: 'forecast_new' },  module: 'forecast', perm: 'forecast:read' },
      { label: 'Forecast Jobs', to: { name: 'forecast_jobs' }, module: 'forecast', perm: 'forecast:read' }
    ]
  },
  {
    label: 'Credit Risk',
    items: [
      { label: 'New Analysis',  to: { name: 'credit_risk_new' },        module: 'credit_risk', perm: 'credit_risk:read' },
      { label: 'Analysis Jobs', to: { name: 'credit_risk_jobs' },       module: 'credit_risk', perm: 'credit_risk:read' },
      { label: 'IFRS 9 ECL',   to: { name: 'credit_risk_ecl' },        module: 'credit_risk', perm: 'credit_risk:read' },
      { label: 'PD / LGD',     to: { name: 'credit_risk_pd_lgd' },     module: 'credit_risk', perm: 'credit_risk:read' },
      { label: 'Transitions',  to: { name: 'credit_risk_transitions' }, module: 'credit_risk', perm: 'credit_risk:read' }
    ]
  },
  {
    label: 'System',
    items: [
      { label: 'User Access Management', to: { name: 'uam' },             module: 'uam',  perm: 'user:read' },
      { label: 'Role Management',        to: { name: 'role-management' }, icon: 'pi pi-shield',              perm: 'role:read' },
      { label: 'Audit Logs',             to: { name: 'log' },             module: 'log',  perm: 'auditlog:read' }
    ]
  }
]

const filteredModel = computed(() =>
  model
    .map((group) => ({ ...group, items: group.items.filter((it) => !it.perm || can(it.perm)) }))
    .filter((group) => group.items.length > 0)
)
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
