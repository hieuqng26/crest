<script setup>
import { ref, computed } from 'vue'
import LineChart from './LineChart.vue'
import { getTransitionLineChartData } from './utils.js'

const props = defineProps({
  data: {
    type: Object,
    required: true
  },
  title: String,
  columns: {
    type: Object,
    required: true
  }
})

const selectedOtherColumn = ref(Object.keys(props.columns)[0])
const selectedOtherChartData = computed(() => {
  if (!props.data || !selectedOtherColumn.value) {
    return []
  }
  return getTransitionLineChartData(props.data, [selectedOtherColumn.value])[0]
})
const selectedUnit = computed(() => props.columns[selectedOtherColumn.value])
</script>

<template>
  <Panel :header="props.title">
    <div class="flex justify-content-center">
      <Dropdown
        v-model="selectedOtherColumn"
        :options="Object.keys(props.columns)"
        placeholder=""
        class="w-full md:w-14rem"
      />
    </div>
    <LineChart :data="selectedOtherChartData" :yTitle="selectedUnit" />
  </Panel>
</template>
