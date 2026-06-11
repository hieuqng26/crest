<script setup>
import { saveFile } from '@/views/composables/views.js'
import { useToast } from 'primevue/usetoast'

const props = defineProps({
  data: {
    type: Object,
    required: false,
    default: null
  },
  filename: {
    type: String,
    required: false,
    default: 'download'
  }
})

const toast = useToast()

// Downloads
const downloadOptions = [
  {
    label: 'csv',
    icon: 'fi fi-rr-file-csv',
    command: () => {
      try {
        saveFile(props.data, 'csv', props.filename || 'download')
      } catch (error) {
        if (!props.data || props.data.length === 0) {
          toast.add({
            severity: 'error',
            summary: 'Error',
            detail: 'No data to download',
            life: 3000
          })
        } else {
          toast.add({
            severity: 'error',
            summary: 'Error',
            detail: 'Fail to download file',
            life: 3000
          })
        }
      }
    }
  },
  {
    label: 'xlsx',
    icon: 'fi fi-rr-file-excel',
    command: () => {
      try {
        saveFile(props.data, 'xlsx', props.filename || 'download')
      } catch (error) {
        if (!props.data || props.data.length === 0) {
          toast.add({
            severity: 'error',
            summary: 'Error',
            detail: 'No data to download',
            life: 3000
          })
        } else {
          toast.add({
            severity: 'error',
            summary: 'Error',
            detail: 'Fail to download file',
            life: 3000
          })
        }
      }
    }
  }
]

const download = () => {
  try {
    saveFile(props.data, 'xlsx', props.filename || 'download')
  } catch (error) {
    if (!props.data || props.data.length === 0) {
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: 'No data to download',
        life: 3000
      })
    } else {
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: 'Fail to download file',
        life: 3000
      })
    }
  }
}
</script>

<template>
  <SplitButton
    label="Save"
    icon=""
    menuButtonIcon="pi pi-download"
    outlined
    :model="downloadOptions"
    @click="download"
  />
</template>
