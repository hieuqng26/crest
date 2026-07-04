<script setup>
import { useRoute } from 'vue-router'
import PageHeader from '@/components/ui/PageHeader.vue'

const route = useRoute()
</script>

<template>
  <div>
    <PageHeader :eyebrow="route.meta.eyebrow" :title="route.meta.title" />
    <div class="coming-soon card--emphasis">
      <i class="pi pi-hourglass coming-soon-icon"></i>
      <p class="coming-soon-text">This screen is part of the v2 redesign and lands in a follow-up pass.</p>
    </div>
  </div>
</template>

<style scoped>
.coming-soon {
  padding: 3rem 2rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  text-align: center;
}
.coming-soon-icon {
  font-size: 1.5rem;
  color: var(--text-color-muted-2);
}
.coming-soon-text {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-color-secondary);
}
</style>
