<script setup>
import { computed } from 'vue'
import { useLayout } from '@/layout/composables/layout'
import { formatNumber } from '../Table/utils'

const { isDarkTheme } = useLayout()

const props = defineProps({
  title: String,
  data: Object,
  options: Object,
  vertical: Boolean,
  height: {
    type: String,
    default: 'h-15rem'
  },
  xUnit: {
    type: String,
    required: false,
    default: 'IDR'
  }
})

const chartOptions = computed(() => {
  const documentStyle = getComputedStyle(document.documentElement)
  const textColor = documentStyle.getPropertyValue('--text-color')
  const textDarkColor = documentStyle.getPropertyValue('--gray-50')
  const surfaceBorder = documentStyle.getPropertyValue('--surface-border')

  return {
    indexAxis: props.vertical ? 'x' : 'y',
    maintainAspectRatio: false,
    aspectRatio: 0.8,
    barThickness: 30,
    plugins: {
      tooltips: {
        mode: 'index',
        intersect: false
      },
      legend: {
        labels: {
          color: isDarkTheme ? textColor : textDarkColor
        }
      }
    },
    scales: {
      x: {
        stacked: true,
        ticks: {
          color: isDarkTheme ? textColor : textDarkColor,
          callback: function (value, index, ticks) {
            let v = formatNumber(value)
            return index % 3 == 0 ? props.xUnit + ' ' + v : ''
          }
        },
        grid: {
          // color: surfaceBorder,
          display: false,
          drawBorder: false
        }
      },
      y: {
        stacked: true,
        ticks: {
          color: isDarkTheme ? textColor : textDarkColor
        },
        grid: {
          color: surfaceBorder,
          drawBorder: false
        }
      }
    },
    ...props.options
  }
})
</script>

<template>
  <Chart type="bar" :data="props.data" :options="chartOptions" :class="props.height" />
</template>
