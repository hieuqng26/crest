<script setup>
import { ref, onMounted } from 'vue'
import AppMenuItem from './AppMenuItem.vue'

const model = [
  // {
  //   label: 'Pricing',
  //   items: [
  //     {
  //       label: 'Single Product',
  //       // icon: 'fi fi-rr-enter',
  //       to: { name: 'pricing_single_product' },
  //       module: 'pricing',
  //       submodule_for_role: 'single_product'
  //     },
  //     {
  //       label: 'Portfolio',
  //       // icon: 'fi fi-rr-grid',
  //       to: { name: 'pricing_portfolio' },
  //       module: 'pricing',
  //       submodule_for_role: 'portfolio'
  //     }
  //   ]
  // },
  // {
  //   label: 'Data',
  //   items: [
  //     {
  //       label: 'Market Data',
  //       // icon: 'pi pi-chart-line',
  //       to: { name: 'market_data' },
  //       module: 'market_data'
  //     }
  //   ]
  // },
  {
    label: 'System',
    items: [
      {
        label: 'User Access Management',
        // icon: 'pi pi-users',
        to: { name: 'uam' },
        module: 'uam'
      },
      {
        label: 'Audit Logs',
        // icon: 'pi pi-history',
        to: { name: 'log' },
        module: 'log',
        submodule_for_role: 'auditlog'
      }
    ]
  }
]

const getSubmodulesForRole = (items) => {
  return items
    .map((item) => {
      // for menu category
      if (item.items) {
        const submodules = getSubmodulesForRole(item.items)
        if (submodules.length > 0) {
          return submodules
        }
      }
      // for each menu item by submodule
      else {
        return [item.module, item.module + '__' + item.submodule_for_role]
      }
      return null
    })
    .filter((item) => item !== null)
}

// Recursive function to filter items based on accessible modules
const filterItems = (items, accessibleModules) => {
  return items
    .map((item) => {
      // for menu category
      if (item.items) {
        const filteredSubItems = filterItems(item.items, accessibleModules)
        if (filteredSubItems.length > 0) {
          return { ...item, items: filteredSubItems }
        }
      }
      // for each menu item by module
      else if (accessibleModules.includes(item.module)) {
        return item
      }
      // for each menu item by submodule
      else if (
        accessibleModules.includes(item.module + '__' + item.submodule_for_role)
      ) {
        return item
      }
      return null
    })
    .filter((item) => item !== null)
}

// Filter the model based on accessible modules
const filteredModel = ref([])

onMounted(() => {
  filteredModel.value = model
})
</script>

<template>
  <ul class="layout-menu">
    <template v-for="(item, i) in filteredModel" :key="item">
      <app-menu-item
        v-if="!item.separator"
        :item="item"
        :index="i"
      ></app-menu-item>
      <li v-if="item.separator" class="menu-separator"></li>
    </template>
  </ul>

  <!-- <Role/> -->
</template>

<style lang="scss" scoped></style>
