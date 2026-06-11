<template>
  <DataTable
    :value="props.data"
    scrollable
    paginator
    :rowHover="true"
    :rows="10"
    :rowsPerPageOptions="[10, 30, 80]"
    tableStyle="min-width: 50rem"
  >
    <ColumnGroup type="header">
      <Row>
        <Column header="Company" :rowspan="3" frozen class="font-bold" />
      </Row>
      <Row>
        <div v-for="col in props.columns" :key="col">
          <Column :header="col" :colspan="props.subColumns.length" />
        </div>
      </Row>
      <Row>
        <div v-for="col in props.columns" :key="col">
          <div v-for="sub in props.subColumns" :key="sub">
            <Column :header="sub" sortable :field="col + sub" />
          </div>
        </div>
      </Row>
    </ColumnGroup>
    <Column field="Company" frozen class="font-bold" />
    <div v-for="col in props.columns" :key="col">
      <div v-for="sub in props.subColumns" :key="sub">
        <Column :field="col + sub">
          <template #body="slotProps"> {{ roundValue(slotProps.data[col + sub]) }} </template>
        </Column>
      </div>
    </div>
  </DataTable>
</template>

<script setup>
const props = defineProps({
  data: {
    type: Object,
    required: true
  },
  columns: {
    type: Object,
    required: true
  },
  subColumns: {
    type: Object,
    required: true
  }
})

const roundValue = (value) => {
  // Check if the value is null or non-numeric
  if (value === null || Number.isNaN(value)) {
    return null
  }
  // Round the value to 3 decimal places
  return Number.parseFloat(value).toFixed(3)
}
</script>
