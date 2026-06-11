<script setup>
import { computed } from 'vue'
import { useLayout } from '@/layout/composables/layout'

const { layoutConfig } = useLayout()
const appName = import.meta.env.VITE_FOOTER

// Logo flips with dark mode: white EY mark on dark backgrounds.
const logoUrl = computed(() =>
  layoutConfig.darkTheme.value
    ? '/layout/images/logo-ey.svg'
    : '/layout/images/logo-ey-dark.svg'
)
</script>

<template>
  <div class="layout-footer">
    <!-- <img :src="logoUrl" alt="Logo" height="20" class="mr-2" />
    by
    <span class="text-lg ml-2">{{ appName }}</span> -->
  </div>
</template>
<style lang="scss" scoped></style>
