<script setup>
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

onMounted(() => {
  router.replace({
    name: 'calibrate_run',
    params: { run_id: route.params.run_id },
    query: { tab: 'diagnostics' }
  })
})
</script>

<template>
  <div class="p-4 text-color-secondary">Redirecting to run diagnostics…</div>
</template>
