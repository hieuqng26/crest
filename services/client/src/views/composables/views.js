// import * as XLSX from 'xlsx'
import ExcelJS from 'exceljs'
import { saveAs } from 'file-saver'

const saveFile = (data, extension, filename = 'download') => {
  if (!data) {
    throw new Error('No data to download')
  }
  if (extension === 'xlsx') {
    downloadXLSX(data, filename)
    return
  } else if (extension === 'csv') {
    downloadCSV(data, filename)
    return
  }
}

const handleDownload = (data, filename) => {
  // Create a blob URL for the data
  const blob = new Blob([data])
  const url = window.URL.createObjectURL(blob)

  // Create a temporary link element
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', filename)

  // Append to the document, trigger the download, and clean up
  document.body.appendChild(link)
  link.click()

  // Clean up
  window.URL.revokeObjectURL(url)
  document.body.removeChild(link)
}

const saveFileMultipleSheets = async (dataDict, extension, filename = 'download') => {
  if (!dataDict) {
    throw new Error('No data to download')
  }

  if (extension === 'csv') {
    throw new Error('CSV format does not support multiple sheets')
  }

  const workbook = new ExcelJS.Workbook()

  for (let [sheetName, data] of Object.entries(dataDict)) {
    let dataOut = data
    // parse json if data is string
    if (typeof dataOut === 'string') {
      dataOut = JSON.parse(dataOut)
    }

    const worksheet = workbook.addWorksheet(sheetName)

    // Add Header Row
    const headers = Object.keys(dataOut[0])
    worksheet.addRow(headers)

    // Add Data Rows
    dataOut.forEach((row) => {
      worksheet.addRow(Object.values(row))
    })

    // Optional: Adjust column widths
    // worksheet.columns.forEach((column) => {
    //   column.width = Math.max(10, ...column.values.map((value) => String(value).length))
    // })
  }

  // Write Workbook and Trigger Download
  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/octet-stream' })
  saveAs(blob, `${filename}.${extension}`)
}

const downloadXLSX = async (data, filename) => {
  const workbook = new ExcelJS.Workbook()
  const worksheet = workbook.addWorksheet('Sheet1')

  // Add Header Row
  const headers = Object.keys(data[0])
  worksheet.addRow(headers)

  // Add Data Rows
  data.forEach((row) => {
    worksheet.addRow(Object.values(row))
  })

  // Set Column Widths for Better Readability (Optional)
  // worksheet.columns.forEach((column) => {
  //   column.width = Math.max(10, ...column.values.map((value) => String(value).length))
  // })

  // Write Workbook and Trigger Download
  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  })
  saveAs(blob, `${filename}.xlsx`)
}

const escapeCSVValue = (value) => {
  if (typeof value === 'string') {
    // Escape double quotes by doubling them
    value = value.replace(/"/g, '""')
    // Wrap the value in double quotes
    return `"${value}"`
  }
  return value
}

const downloadCSV = (data, filename) => {
  const csvContent = [
    Object.keys(data[0]).map(escapeCSVValue).join(','), // header
    ...data.map((row) => Object.values(row).map(escapeCSVValue).join(',')) // rows
  ].join('\n')

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  saveAs(blob, `${filename}.csv`)
}

// const downloadXLSXChunk = (data, filename) => {
//   const workbook = { Sheets: {}, SheetNames: [] }

//   const chunkSize = 10000 // Adjust based on performance
//   for (let i = 0; i < data.length; i += chunkSize) {
//     const chunk = data.slice(i, i + chunkSize)
//     const sheetName = `Sheet${workbook.SheetNames.length + 1}`
//     workbook.Sheets[sheetName] = XLSX.utils.json_to_sheet(chunk)
//     workbook.SheetNames.push(sheetName)
//   }

//   const xlsxData = XLSX.write(workbook, { bookType: 'xlsx', type: 'array', bookSST: true })

//   const blob = new Blob([xlsxData], { type: 'application/octet-stream' })
//   saveAs(blob, `${filename}.xlsx`)
// }

// const saveFileMultipleSheets = (dataDict, extension, filename = 'download') => {
//   if (!dataDict) {
//     throw new Error('No data to download')
//   }
//   const wb = XLSX.utils.book_new()
//   for (let [key, data] of Object.entries(dataDict)) {
//     let dataOut = data
//     // parse json if data is string
//     if (typeof dataOut === 'string') {
//       dataOut = JSON.parse(dataOut)
//     }
//     const ws = XLSX.utils.json_to_sheet(dataOut)
//     XLSX.utils.book_append_sheet(wb, ws, key)
//   }
//   XLSX.writeFile(wb, filename + '.' + extension)
// }

export { saveFile, saveFileMultipleSheets, handleDownload }
