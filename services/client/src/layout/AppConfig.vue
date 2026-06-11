<script setup>
import { onMounted } from 'vue'
import { useLayout } from '@/layout/composables/layout'

const { layoutConfig } = useLayout()

onMounted(() => {
  applyScale()
})

const applyScale = () => {
  document.documentElement.style.fontSize = layoutConfig.scale.value + 'px'
}
</script>

<template></template>
