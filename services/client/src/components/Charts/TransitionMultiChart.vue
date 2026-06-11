<script setup>
import { ref, computed } from 'vue'
import LineChart from './LineChart.vue'
import GroupChart from './GroupChart.vue'
import { getTransitionLineChartData } from './utils.js'

const props = defineProps({
  data: {
    type: Object,
    required: true
  },
  mainColumns: {
    type: Object,
    default: {}
  },
  xCol: {
    type: String,
    default: 'YEAR'
  },
  legendCol: {
    type: String,
    default: 'SCENARIO'
  },
  groups: {
    type: Object,
    default: {}
  },
  chartPerRow: {
    type: Number,
    default: 2
  }
})

// Chart Layout
const chartClass = computed(() => {
  const chartLgClass = 'lg:col-' + 12 / props.chartPerRow
  const chartMdClass = 'col-' + 12
  return chartLgClass + ' ' + chartMdClass
})

// Generate Chart Data
const chartDataList = computed(() => {
  const columns = Object.keys(props.mainColumns)
  if (!props.data || !columns) {
    return []
  }

  return getTransitionLineChartData(props.data, columns, props.xCol, props.legendCol)
})

const mainColumns = computed(() => props.mainColumns)
</script>

<template>
  <div class="grid">
    <div v-for="i in chartDataList.length" :key="i" :class="chartClass">
      <!-- <Panel> </Panel> -->
      <LineChart
        :data="chartDataList[i - 1]"
        :title="
          Object.keys(mainColumns)[i - 1].replace(/_/g, ' ') +
          ' ' +
          Object.values(mainColumns)[i - 1]
        "
      />
    </div>

    <div v-for="gr in Object.keys(groups)" :key="gr" :class="chartClass">
      <div v-if="props.data && groups[gr]">
        <GroupChart :data="props.data" :title="gr" :columns="groups[gr]" />
      </div>
    </div>
  </div>
</template>
