// Chart colors
const documentStyle = getComputedStyle(document.documentElement)

const scenarioOrder = [
  'Current Policies',
  'NDCs',
  'Delayed Transition',
  'Fragmented World',
  'Below 2C',
  'Net Zero 2050',
  'Target'
]

const transitionScenarioBorderColors = {
  'Net Zero 2050': documentStyle.getPropertyValue('--cyan-500'),
  'Delayed Transition': documentStyle.getPropertyValue('--green-500'),
  'Below 2C': documentStyle.getPropertyValue('--yellow-500'),
  NDCs: documentStyle.getPropertyValue('--indigo-500'),
  'Fragmented World': documentStyle.getPropertyValue('--red-500'),
  'Current Policies': documentStyle.getPropertyValue('--gray-500'),
  Target: documentStyle.getPropertyValue('--orange-500')
}

const transitionScenarioBgColors = {
  'Net Zero 2050': documentStyle.getPropertyValue('--cyan-400'),
  'Delayed Transition': documentStyle.getPropertyValue('--green-400'),
  'Below 2C': documentStyle.getPropertyValue('--yellow-400'),
  NDCs: documentStyle.getPropertyValue('--indigo-400'),
  'Fragmented World': documentStyle.getPropertyValue('--red-400'),
  'Current Policies': documentStyle.getPropertyValue('--gray-400'),
  Target: documentStyle.getPropertyValue('--orange-400')
}

const physicalScenarioBorderColors = {
  rcp4p5: documentStyle.getPropertyValue('--cyan-500'),
  rcp8p5: documentStyle.getPropertyValue('--green-500')
}

const physicalScenarioBgColors = {
  rcp4p5: documentStyle.getPropertyValue('--cyan-400'),
  rcp8p5: documentStyle.getPropertyValue('--green-400')
}

const getTransitionLineChartData = (
  data,
  yColumns,
  xcol = 'YEAR',
  legendCol = 'SCENARIO',
  sortX = true
) => {
  // transform data from
  // input format: Array of objects {SCENARIO: ..., YEAR: ..., column1: ..., column2: ...}
  // output format: Array of objects {labels: [years], datasets: [{label: scenario, data: [values]}]} for each column in columns
  if (sortX) {
    data = data.sort((a, b) => a[xcol] - b[xcol])
  }
  const labels = [...new Set(data.map((item) => item[xcol]))]
  let legends = [...new Set(data.map((item) => item[legendCol]))]

  // Sort legends by the defined scenario order only if legendCol is 'SCENARIO'
  let sortedLegends = legends
  if (legendCol === 'SCENARIO') {
    sortedLegends = legends.sort((a, b) => {
      const indexA = scenarioOrder.indexOf(a)
      const indexB = scenarioOrder.indexOf(b)
      // If scenario not in order list, put it at the end
      if (indexA === -1) return 1
      if (indexB === -1) return -1
      return indexA - indexB
    })
  }

  return yColumns.map((col) => {
    const datasets = sortedLegends.map((legend) => {
      return {
        label: legend,
        data: data.filter((item) => item[legendCol] == legend).map((item) => item[col]),
        fill: false,
        borderColor: transitionScenarioBorderColors[legend],
        backgroundColor: transitionScenarioBgColors[legend],
        // pointStyle: 'rectRot',
        tension: 0.0,
        pointRadius: 2
      }
    })
    return {
      labels: labels,
      datasets: datasets
    }
  })
}

const getPhysicalLineChartData = (data, xCol, yColumns) => {
  // transform data from
  // input format: Array of objects {SCENARIO, return_period, hazard_intensity, Asset}
  // output format: Array of objects {labels: [return_period], datasets: [{label: SCENARIO, data: [values]}]} for each column in yColumns
  const labels = [...new Set(data.map((item) => item[xCol]))]
  const scenarios = [...new Set(data.map((item) => item.SCENARIO))]

  return yColumns.map((col) => {
    const datasets = scenarios.map((scen) => {
      return {
        label: scen,
        data: data.filter((item) => item.SCENARIO == scen).map((item) => item[col]),
        fill: false,
        borderColor: physicalScenarioBorderColors[scen],
        backgroundColor: physicalScenarioBgColors[scen],
        tension: 0.0,
        pointRadius: 2.3
      }
    })
    return {
      labels: labels,
      datasets: datasets
    }
  })
}

const getPhysicalBarChartData = (data, labelColumn, valueColumns) => {
  const labels = [...new Set(data.map((item) => item[labelColumn]))]
  const colors = [
    documentStyle.getPropertyValue('--orange-500'),
    documentStyle.getPropertyValue('--teal-800')
  ]
  const colorMap = valueColumns.reduce((acc, label, idx) => {
    acc[label] = colors[idx]
    return acc
  }, {})

  const datasets = valueColumns.map((label) => {
    return {
      type: 'bar',
      label: label.split('_').join(' '),
      backgroundColor: colorMap[label],
      data: data.map((item) => item[label]),
      barThickness: 18
    }
  })

  return {
    labels: labels,
    datasets: datasets
  }
}

const getAssetFlowData = (data, legendColumn, yColumns) => {
  // transform data from
  // input format: Array of objects {SCENARIO, YEAR, yColumns}
  // output format: Array of objects {labels: [years], datasets: [{label: SCENARIO, data: [values]}]} for each column in columns
  const sortedData = data.sort((a, b) => a.YEAR - b.YEAR)
  const labels = [...new Set(sortedData.map((item) => item.YEAR))]
  const legends = [...new Set(sortedData.map((item) => item[legendColumn]))]

  return yColumns.map((col) => {
    const datasets = legends.map((legend) => {
      return {
        label: legend,
        data: sortedData.filter((item) => item[legendColumn] == legend).map((item) => item[col]),
        fill: false,
        borderColor: physicalScenarioBorderColors[legend],
        backgroundColor: physicalScenarioBorderColors[legend],
        tension: 0.0,
        pointRadius: 1
      }
    })
    return {
      labels: labels,
      datasets: datasets
    }
  })
}

const getPhysicalBarChartSummaryData = (data) => {
  const flood45 = data
    .filter((item) => (item.SCENARIO === 'rcp4p5') & (item.HAZARD_TYPE === 'Flood'))
    .map((d) => d.impact_value)
  const flood85 = data
    .filter((item) => (item.SCENARIO === 'rcp8p5') & (item.HAZARD_TYPE === 'Flood'))
    .map((d) => d.impact_value)
  const tc45 = data
    .filter((item) => (item.SCENARIO === 'rcp4p5') & (item.HAZARD_TYPE === 'TropicalCyclone'))
    .map((d) => d.impact_value)
  const tc85 = data
    .filter((item) => (item.SCENARIO === 'rcp8p5') & (item.HAZARD_TYPE === 'TropicalCyclone'))
    .map((d) => d.impact_value)

  return {
    labels: [...new Set(data.map((item) => item.Asset))],
    datasets: [
      {
        type: 'bar',
        label: 'Flood4.5',
        backgroundColor: documentStyle.getPropertyValue('--blue-300'),
        data: flood45,
        stack: 'rcp4.5'
      },
      {
        type: 'bar',
        label: 'TC4.5',
        backgroundColor: documentStyle.getPropertyValue('--green-300'),
        data: tc45,
        stack: 'rcp4.5'
      },
      {
        type: 'bar',
        label: 'Flood8.5',
        backgroundColor: documentStyle.getPropertyValue('--blue-600'),
        data: flood85,
        stack: 'rcp8.5'
      },
      {
        type: 'bar',
        label: 'TC8.5',
        backgroundColor: documentStyle.getPropertyValue('--green-600'),
        data: tc85,
        stack: 'rcp8.5'
      }
    ]
  }
}

const getSectorScoreBarChartData = (data, labelColumn, valueColumns) => {
  const labels = [...new Set(data.map((item) => item[labelColumn]))]
  const colors = [documentStyle.getPropertyValue('--blue-500')]
  const colorMap = valueColumns.reduce((acc, label, idx) => {
    acc[label] = colors[idx]
    return acc
  }, {})

  const datasets = valueColumns.map((label) => {
    return {
      type: 'bar',
      label: label.split('_').join(' '),
      backgroundColor: colorMap[label],
      // data: y.map((item) => item[label]),
      data: data.map((item) => item[label]),
      barThickness: 18
    }
  })

  return {
    labels: labels,
    datasets: datasets
  }
}

export {
  getTransitionLineChartData,
  getPhysicalLineChartData,
  getPhysicalBarChartData,
  getPhysicalBarChartSummaryData,
  getAssetFlowData,
  getSectorScoreBarChartData
}
