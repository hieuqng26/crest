<script setup>
import SimpleTable from '@/components/Table/SimpleTable.vue'

const props = defineProps({
  data: {
    type: Object,
    required: true
  },
  header: {
    type: String,
    required: false
  }
})

// methods
const getData = (key) => {
  if (!props.data) return null
  return props.data[key]
}
</script>

<template>
  <div>
    <TabView :scrollable="true">
      <TabPanel v-if="props.data" v-for="key in Object.keys(props.data)" :key="key" :header="key">
        <SimpleTable :data="getData(key)" />
      </TabPanel>
    </TabView>
  </div>
</template>
