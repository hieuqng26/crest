<script setup>
import { computed } from 'vue'
import { useLayout } from '@/layout/composables/layout'

const { isDarkTheme } = useLayout()

const props = defineProps({
  title: String,
  data: Object,
  onClickFunction: Function // need to check if the type is ok
})

const chartOptions = computed(() => {
  const documentStyle = getComputedStyle(document.documentElement)
  const textColor = documentStyle.getPropertyValue('--text-color')
  const textDarkColor = documentStyle.getPropertyValue('--gray-50')
  const surfaceBorder = documentStyle.getPropertyValue('--surface-border')
  const maxLabelLength = Math.max(...props.data.labels.map((label) => label.length))
  const maxLength = 25 // Maximum length of the label before truncating

  // Set rotation based on label length
  const rotation = maxLabelLength > maxLength ? 60 : 0

  return {
    indexAxis: 'x',
    maintainAspectRatio: false,
    aspectRatio: 0.6,
    barThickness: 30,
    onClick: props.onClickFunction,
    plugins: {
      tooltips: {
        mode: 'index',
        intersect: false
      },
      legend: {
        display: false
      }
    },
    scales: {
      x: {
        stacked: false,
        ticks: {
          color: isDarkTheme ? textColor : textDarkColor,
          autoskip: false,
          maxRotation: rotation,
          minRotation: rotation,
          callback: function (i) {
            let value = props.data.labels[i]
            if (value.length > maxLength) {
              return value.substr(0, maxLength) + '...'
            } else {
              return value
            }
          }
        },
        grid: {
          color: surfaceBorder,
          drawBorder: false
        }
      },
      y: {
        stacked: false,
        ticks: {
          color: isDarkTheme ? textColor : textDarkColor,
          callback: function (value, index, ticks) {
            return value + '℃'
          }
        },
        grid: {
          // color: surfaceBorder,
          display: false,
          drawBorder: false
        }
      }
    }
  }
})
</script>

<template>
  <div class="chart-container">
    <Chart type="bar" :data="props.data" :options="chartOptions" class="chart" />
  </div>
</template>

<style scoped>
.chart-container {
  height: 60vh;
  display: flex;
  justify-content: center;
  align-items: center;
}

.chart {
  width: 100%;
  height: 100%;
}
</style>
