<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  totalRecords: Number,
  perPage: Number,
  currentPage: Number
})

const emit = defineEmits(['update:currentPage'])

const currentPage = ref(props.currentPage)
const totalPages = computed(() => Math.ceil(props.totalRecords / props.perPage) - 1)

const toFirst = () => {
  currentPage.value = 0
}
const toPrev = () => {
  currentPage.value = currentPage.value - 1
}
const toNext = () => {
  currentPage.value = currentPage.value + 1
}
const toLast = () => {
  currentPage.value = Math.ceil(props.totalRecords / props.perPage) - 1
}

// Watch for changes in currentPage and emit the event
watch(currentPage, (p) => {
  emit('update:currentPage', p)
})

// Watch for changes in props.currentPage and update the currentPage value
watch(
  () => props.currentPage,
  (p) => {
    currentPage.value = p
  },
  { immediate: true }
)
</script>

<template>
  <div class="flex gap-2 justify-items-center align-items-center">
    <Button
      icon="pi pi-angle-double-left"
      text
      rounded
      severity="secondary"
      @click="toFirst()"
      :disabled="currentPage == 0"
    />
    <Button
      icon="pi pi-angle-left"
      text
      rounded
      severity="secondary"
      @click="toPrev()"
      :disabled="currentPage == 0"
    />
    <div>
      <span>{{ currentPage + 1 }} of {{ totalPages + 1 }}</span>
    </div>
    <Button
      icon="pi pi-angle-right"
      text
      rounded
      severity="secondary"
      @click="toNext()"
      :disabled="currentPage == totalPages"
    />
    <Button
      icon="pi pi-angle-double-right"
      text
      rounded
      severity="secondary"
      @click="toLast()"
      :disabled="currentPage == totalPages"
    />
  </div>
</template>
