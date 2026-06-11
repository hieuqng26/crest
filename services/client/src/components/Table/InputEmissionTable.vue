<script setup>
import { computed, ref } from 'vue'
import { formatCurrency, formatPercentage } from './utils.js'
import { FilterMatchMode } from 'primevue/api'
import DownloadButton from '@/components/Button/DownloadButton.vue'

const props = defineProps({
  data: {
    type: Array,
    required: true
  },
  module: String,
  currencyColumns: {
    type: Array,
    default: () => []
  },
  percentColumns: {
    type: Object,
    default: () => {}
  },
  nonEditableColumns: {
    type: Array,
    default: () => []
  },
  hideColumns: {
    type: Array,
    default: () => []
  }
})

const columns = computed(() => {
  if (!props.data) {
    return []
  }
  const ret = Object.keys(props.data[0])
    .filter((k) => props.hideColumns.includes(k) === false)
    .map((key) => {
      return {
        field: key,
        header: key,
        sortable: true
      }
    })

  return ret
})

const globalFilterFields = computed(() => {
  if (!props.data) {
    return []
  }
  // get all columns except id
  const ret = Object.keys(props.data[0])
  return ret
})

const filters = ref(null)
const initFilters = () => {
  filters.value = {
    global: { value: null, matchMode: FilterMatchMode.STARTS_WITH }
  }

  if (props.data && Array.isArray(props.data) && props.data.length > 0) {
    Object.keys(props.data[0]).forEach((key) => {
      filters.value[key] = { value: null, matchMode: FilterMatchMode.STARTS_WITH }
    })
  }
}

initFilters()

const clearFilter = () => {
  // set value to null for all filters
  Object.keys(filters.value).forEach((key) => {
    filters.value[key].value = null
  })
}

//-------Cell Edit--------//
const emit = defineEmits(['update:table'])

const onCellEditComplete = (event) => {
  let { data, newValue, field } = event
  const percentColumns = props.percentColumns.map((d) => d.name)

  // check if the value has changed
  if (data[field] !== newValue) {
    if (props.nonEditableColumns.includes(field)) {
      return
    } else {
      data[field] = newValue
    }

    // use axios to update the data
    emit('update:table', props.data)
  }
}
</script>

<template>
  <div>
    <DataTable
      v-if="props.data"
      :value="props.data"
      v-model:filters="filters"
      filterDisplay="row"
      :globalFilterFields="globalFilterFields"
      sortMode="multiple"
      removableSort
      paginator
      :rowHover="true"
      :rows="10"
      :rowsPerPageOptions="[10, 30, 80]"
      editMode="cell"
      @cell-edit-complete="onCellEditComplete"
      :pt="{
        // table: { style: 'min-width: 50rem' },
        column: {
          bodycell: ({ state }) => ({
            class: [{ 'pt-0 pb-0': state['d_editing'] }]
          })
        }
      }"
    >
      <!-- <template #header>
        <div class="flex justify-content-between flex-column sm:flex-row">
          <Button
            type="button"
            icon="pi pi-filter-slash"
            label="Clear"
            outlined
            @click="clearFilter()"
          />
          <IconField iconPosition="left">
            <InputIcon class="pi pi-search" />
            <InputText
              v-model="filters['global'].value"
              placeholder="Start with"
              style="width: 100%"
            />
          </IconField>
        </div>
      </template> -->

      <Column v-for="col of columns" :key="col.field" :field="col.field" :header="col.header">
        <template #body="{ data, field }">
          {{
            props.percentColumns.map((d) => d.name).includes(field)
              ? formatPercentage(
                  data[field],
                  props.percentColumns.filter((d) => d.name === field)[0].maxDigits
                )
              : props.currencyColumns.includes(field)
                ? formatCurrency(data[field])
                : data[field]
          }}
        </template>
        <template #editor="{ data, field }">
          <template v-if="props.nonEditableColumns.includes(field)">
            <span>{{ data[field] }}</span>
          </template>
          <template v-else-if="props.currencyColumns.includes(field)">
            <InputNumber
              v-model="data[field]"
              mode="currency"
              currency="USD"
              locale="en-US"
              autofocus
            />
          </template>
          <template v-else-if="props.percentColumns.map((d) => d.name).includes(field)">
            <InputNumber
              v-model="data[field]"
              locale="en-US"
              autofocus
              :min="0"
              :max="1"
              :minFractionDigits="2"
              :maxFractionDigits="4"
              fluid
            />
          </template>
          <template v-else>
            <span>{{ data[field] }}</span>
          </template>
        </template>
      </Column>
      <template #paginatorstart>
        <DownloadButton :data="props.data" :filename="props.module + '_input_targets'" />
      </template>
    </DataTable>
  </div>
</template>
