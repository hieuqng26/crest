import { interpolateColor } from './colorGenerator'

const ranges = [
  [0.0, 0.05],
  [0.05, 0.1],
  [0.1, 0.15],
  [0.15, 0.2],
  [0.2, 0.25],
  [0.25, 0.3],
  [0.3, 0.35],
  [0.35, 0.4],
  [0.4, 0.45],
  [0.45, 0.5],
  [0.5, 0.55],
  [0.55, 0.6],
  [0.6, 0.65],
  [0.65, 0.7],
  [0.7, 0.75],
  [0.75, 0.8],
  [0.8, 0.85],
  [0.85, 0.9],
  [0.9, 0.95],
  [0.95, 1]
]

const lightColors = [
  '#F8696B',
  '#F9776E',
  '#FA8571',
  '#FB9373',
  '#FBA076',
  '#FCAE79',
  '#FDBC7B',
  '#FEC97E',
  '#FED781',
  '#FFE583',
  '#F6E883',
  '#E6E382',
  '#D5DF81',
  '#C5DA80',
  '#B5D57F',
  '#A4D07E',
  '#94CC7D',
  '#83C77C',
  '#73C27B',
  '#63BE7B'
]

const startColorDark = '#004C70'
const endColorDark = '#7FDBFF'
const steps = 20

const darkColors = Array.from({ length: steps }, (_, i) =>
  interpolateColor(startColorDark, endColorDark, i / (steps - 1))
)

const colorScaleLight = ranges.map((range, index) => {
  return {
    from: range[0],
    to: range[1],
    color: lightColors[index],
    name: null
  }
})

const colorScaleDark = ranges.map((range, index) => {
  return {
    from: range[0],
    to: range[1],
    color: darkColors[index],
    name: null
  }
})

const documentStyle = getComputedStyle(document.documentElement)
const textLight = documentStyle.getPropertyValue('--gray-100')
const textDark = documentStyle.getPropertyValue('--gray-800')

export { colorScaleLight, colorScaleDark, textLight, textDark }
