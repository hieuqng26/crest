<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { FilterMatchMode } from 'primevue/api'
import { formatCurrency } from '@/components/Table/utils'
import DownloadButton from '@/components/Button/DownloadButton.vue'

const props = defineProps({
  data: {
    type: Array,
    required: true
  },
  downloadFileName: {
    type: String,
    required: false,
    default: 'download'
  }
})

// Table
const dt = ref(null)
const currencyColumns = ref([''])
const data = ref(null)
const filters = ref(null)

//-------Filters-------//
const initFilters = () => {
  filters.value = {
    global: { value: null, matchMode: FilterMatchMode.STARTS_WITH }
  }

  if (data.value && Array.isArray(data.value) && data.value.length > 0) {
    Object.keys(data.value[0]).forEach((key) => {
      filters.value[key] = { value: null, matchMode: FilterMatchMode.STARTS_WITH }
    })
  }
}

const globalFilterFields = computed(() => {
  if (!data.value || !data.value[0]) {
    return []
  }
  // get all columns except id
  const ret = Object.keys(data.value[0])
  return ret
})

// const clearFilter = () => {
//   // set value to null for all filters
//   Object.keys(filters.value).forEach((key) => {
//     filters.value[key].value = null
//   })
// }

//-------Process-------//
onMounted(() => {
  data.value = props.data
  initFilters()
})

watch(
  () => props.data,
  (newData) => {
    data.value = newData
    initFilters()
  },
  { immediate: true }
)

//-------Columns-------//
const columns = computed(() => {
  if (!data.value || !data.value[0]) {
    return []
  }

  const ret = Object.keys(data.value[0]).map((key) => {
    return {
      field: key,
      header: key,
      sortable: true
    }
  })

  return ret
})
</script>

<template>
  <div>
    <DataTable
      v-if="data && Array.isArray(data)"
      :value="data"
      ref="dt"
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
      resizableColumns
      columnResizeMode="fit"
      tableStyle="min-width: 100rem"
      paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
      currentPageReportTemplate="Showing {first} to {last} of {totalRecords} rows"
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

      <Column
        v-for="col of columns"
        :key="col.field"
        :field="col.field"
        :header="col.header"
        :sortable="col.sortable"
        :filterField="col.field"
        style="min-width: 15rem"
      >
        <template #body="{ data, field }">
          {{ currencyColumns.includes(field) ? formatCurrency(data[field]) : data[field] }}
        </template>
        <!-- <template #editor="{ data, field }">
          <template v-if="!currencyColumns.includes(field)">
            <InputText v-model="data[field]" autofocus />
          </template>
          <template v-else>
            <InputNumber
              v-model="data[field]"
              mode="currency"
              currency="USD"
              locale="en-US"
              autofocus
            />
          </template>
        </template> -->
        <template #filter="{ filterModel, filterCallback }">
          <InputText
            v-model="filterModel.value"
            type="text"
            @input="filterCallback()"
            class="p-column-filter"
            placeholder="Search"
          />
        </template>
      </Column>

      <template #paginatorstart>
        <DownloadButton :data="data" :filename="props.downloadFileName" />
      </template>
    </DataTable>
  </div>
</template>
