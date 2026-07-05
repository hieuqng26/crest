<script setup>
import { computed } from 'vue'
import { useStore } from 'vuex'
import AppMenuItem from './AppMenuItem.vue'

const store = useStore()
const can = (p) => store.getters.can(p)

// v2 IA: OVERVIEW / DATA / MODEL / ANALYSIS / JOBS / SYSTEM.
// New-model, model-results, heatmap, financial-forecast and job-history/detail
// routes resolve to a ComingSoon placeholder until their screens are built —
// see router/index.js.
const model = [
  {
    label: 'Overview',
    items: [
      { label: 'Dashboard', icon: 'pi pi-fw pi-home', to: { name: 'dashboard' } }
    ]
  },
  {
    label: 'Data',
    items: [
      { label: 'Datasets', icon: 'pi pi-fw pi-database', to: { name: 'datasets' }, perm: 'dataset:read' }
    ]
  },
  {
    label: 'Model',
    items: [
      { label: 'New Model',      icon: 'pi pi-fw pi-plus-circle', to: { name: 'model_new' },           perm: 'calibration:read' },
      { label: 'Configurations', icon: 'pi pi-fw pi-sliders-h',   to: { name: 'model_configurations' }, perm: 'model_config:read' },
      { label: 'Model Results',  icon: 'pi pi-fw pi-chart-bar',   to: { name: 'model_results' },        perm: 'calibration:read' }
    ]
  },
  {
    label: 'Analysis',
    items: [
      { label: 'Heatmap',            icon: 'pi pi-fw pi-th-large',  to: { name: 'analysis_heatmap' },       perm: 'credit_risk:read' },
      { label: 'Financial Forecast', icon: 'pi pi-fw pi-chart-line', to: { name: 'analysis_forecast' },      perm: 'credit_risk:read' },
      { label: 'PD / LGD',           icon: 'pi pi-fw pi-percentage', to: { name: 'credit_risk_pd_lgd' },     perm: 'credit_risk:read' },
      { label: 'IFRS 9 ECL',         icon: 'pi pi-fw pi-calculator', to: { name: 'credit_risk_ecl' },        perm: 'credit_risk:read' },
      { label: 'Transitions',        icon: 'pi pi-fw pi-arrows-h',   to: { name: 'credit_risk_transitions' }, perm: 'credit_risk:read' }
    ]
  },
  {
    label: 'Jobs',
    items: [
      { label: 'Job History', icon: 'pi pi-fw pi-history', to: { name: 'jobs_history' }, perm: 'calibration:read' }
    ]
  },
  {
    label: 'System',
    items: [
      { label: 'User Access Management', icon: 'pi pi-fw pi-users',  to: { name: 'uam' },             perm: 'user:read' },
      { label: 'Role Management',        icon: 'pi pi-fw pi-shield', to: { name: 'role-management' }, perm: 'role:read' },
      { label: 'Audit Logs',             icon: 'pi pi-fw pi-list',   to: { name: 'log' },             perm: 'auditlog:read' }
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
