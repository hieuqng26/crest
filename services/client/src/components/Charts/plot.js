export const createDonutChart = (values, colors, percentiles) => {
  // find unit to nicely format big numbers
  var unit = 1
  var unitStr = ''

  const totalValue = values.reduce((a, b) => a + b, 0)
  if (totalValue === 0) {
    return '' // Handle the case where all values are zero (no pie chart)
  }

  if (totalValue < 1000000) {
    unit = 1
    unitStr = ''
  } else {
    unit = 1000000
    unitStr = 'Jt'
  }

  values = values.map((v) => v / unit)
  var offsets = []
  var scaledTotal = 0
  for (var i = 0; i < values.length; i++) {
    offsets.push(scaledTotal)
    scaledTotal += values[i]
  }
  var total = (totalValue / unit).toFixed(0)

  // format size of the pie charts
  var fontSize =
    total > percentiles[7]
      ? 28
      : total > percentiles[6]
        ? 26
        : total > percentiles[5]
          ? 24
          : total > percentiles[4]
            ? 22
            : total > percentiles[3]
              ? 20
              : total >= percentiles[2]
                ? 18
                : total >= percentiles[1]
                  ? 16
                  : total >= percentiles[0]
                    ? 14
                    : 12
  var r =
    totalValue >= percentiles[7]
      ? 65
      : totalValue >= percentiles[6]
        ? 60
        : totalValue >= percentiles[5]
          ? 55
          : totalValue >= percentiles[4]
            ? 50
            : totalValue >= percentiles[3]
              ? 45
              : totalValue >= percentiles[2]
                ? 40
                : totalValue >= percentiles[1]
                  ? 35
                  : totalValue >= percentiles[0]
                    ? 30
                    : 25

  var r0 = Math.round(r * 0.6)
  var w = r * 2

  // create the svg
  var html =
    '<div><svg width="' +
    w +
    '" height="' +
    w +
    '" viewbox="0 0 ' +
    w +
    ' ' +
    w +
    '" text-anchor="middle" style="font: ' +
    fontSize +
    'px sans-serif; display: block">'

  for (i = 0; i < values.length; i++) {
    html += donutSegment(
      offsets[i] / scaledTotal,
      (offsets[i] + values[i]) / scaledTotal,
      r,
      r0,
      colors[i]
    )
  }
  html +=
    '<circle cx="' +
    r +
    '" cy="' +
    r +
    '" r="' +
    r0 +
    '" fill="white" /><text dominant-baseline="central" transform="translate(' +
    r +
    ', ' +
    r +
    ')">' +
    'Rp.' +
    total.toLocaleString() +
    unitStr +
    '</text></svg></div>'
  var el = document.createElement('div')
  el.innerHTML = html

  return el.firstChild
}

const donutSegment = (start, end, r, r0, color) => {
  if (end === start) {
    // Skip segments with no size
    return ''
  }

  // Avoid full circle edge case by leaving tiny gap
  if (end - start >= 0.9999) {
    end = 0.9999
  }

  var a0 = 2 * Math.PI * (start - 0.25)
  var a1 = 2 * Math.PI * (end - 0.25)
  var x0 = Math.cos(a0)
  var y0 = Math.sin(a0)
  var x1 = Math.cos(a1)
  var y1 = Math.sin(a1)
  var largeArc = end - start > 0.5 ? 1 : 0

  return [
    '<path d="M',
    r + r0 * x0,
    r + r0 * y0,
    'L',
    r + r * x0,
    r + r * y0,
    'A',
    r,
    r,
    0,
    largeArc,
    1,
    r + r * x1,
    r + r * y1,
    'L',
    r + r0 * x1,
    r + r0 * y1,
    'A',
    r0,
    r0,
    0,
    largeArc,
    0,
    r + r0 * x0,
    r + r0 * y0,
    '" fill="' + color + '" />'
  ].join(' ')
}

export const calculatePercentiles = (arr, n) => {
  // if (arr.length < n) {
  //   n = arr.length
  // }

  arr.sort((a, b) => a - b)
  const deciles = []
  for (let i = 1; i < n; i++) {
    const pos = (i * arr.length) / n
    const base = Math.floor(pos)
    const rest = pos - base

    if (base + 1 < arr.length) {
      deciles.push(arr[base] + rest * (arr[base + 1] - arr[base]))
    } else {
      deciles.push(arr[base])
    }
  }

  return deciles
}
