<script setup>
import { ref, computed, onMounted } from 'vue'
import { useToast } from 'primevue/usetoast'
import { FilterMatchMode } from 'primevue/api'
import segmentationConfigsAPI from '@/api/segmentationConfigsAPI'
import { fmtDate } from '@/utils/datetime'

const toast = useToast()

const SPLIT_OPTIONS = [
  { label: 'Subsector', value: 'subsector' },
  { label: 'Country',   value: 'country' },
]

// ---- Data ----
const rows = ref([])
const loading = ref(false)

const load = async () => {
  loading.value = true
  try {
    const { data } = await segmentationConfigsAPI.list()
    rows.value = data
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ---- Filter ----
const filters = ref({ global: { value: '', matchMode: FilterMatchMode.CONTAINS } })

const filteredRows = computed(() => {
  const q = filters.value.global.value?.toLowerCase() ?? ''
  if (!q) return rows.value
  return rows.value.filter(r =>
    ['name', 'description', 'default_split', 'created_by'].some(f =>
      String(r[f] ?? '').toLowerCase().includes(q)
    )
  )
})

// ---- Selection ----
const selection = ref([])

// ---- Dialog (create + edit) ----
const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)

const blankForm = () => ({
  name: '',
  description: '',
  default_split: 'subsector',
  max_segments: 5,
  sector_rules: [],
})

const form = ref(blankForm())

const openCreate = () => {
  editingId.value = null
  form.value = blankForm()
  dialogVisible.value = true
}

const openEdit = (row) => {
  editingId.value = row.id
  form.value = {
    name: row.name,
    description: row.description ?? '',
    default_split: row.default_split,
    max_segments: row.max_segments,
    sector_rules: (row.sector_rules ?? []).map(r => ({ ...r })),
  }
  dialogVisible.value = true
}

const addSectorRule = () => {
  form.value.sector_rules.push({ sector: '', split_by: 'subsector', max_segments: form.value.max_segments })
}

const removeSectorRule = (idx) => {
  form.value.sector_rules.splice(idx, 1)
}

const saveDialog = async () => {
  if (!form.value.name.trim()) {
    toast.add({ severity: 'warn', summary: 'Required', detail: 'Name is required', life: 3000 })
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      description: form.value.description || null,
      default_split: form.value.default_split,
      max_segments: Number(form.value.max_segments),
      sector_rules: form.value.sector_rules.filter(r => r.sector.trim()),
    }
    if (editingId.value) {
      const { data } = await segmentationConfigsAPI.update(editingId.value, payload)
      const idx = rows.value.findIndex(r => r.id === editingId.value)
      if (idx !== -1) rows.value[idx] = data
      toast.add({ severity: 'success', summary: 'Updated', detail: data.name, life: 3000 })
    } else {
      const { data } = await segmentationConfigsAPI.create(payload)
      rows.value.unshift(data)
      toast.add({ severity: 'success', summary: 'Created', detail: data.name, life: 3000 })
    }
    dialogVisible.value = false
  } catch (e) {
    toast.add({ severity: 'error', summary: 'Save failed', detail: e?.response?.data?.error ?? e.message, life: 4000 })
  } finally {
    saving.value = false
  }
}

// ---- Delete ----
const confirmDeleteId = ref(null)
const deleteDialogVisible = ref(false)
const deleteTargetName = ref('')
const deleting = ref(false)

const openDelete = (row) => {
  confirmDeleteId.value = row.id
  deleteTargetName.value = row.name
  deleteDialogVisible.value = true
}

const confirmDelete = async () => {
  deleting.value = true
  try {
    await segmentationConfigsAPI.delete(confirmDeleteId.value)
    rows.value = rows.value.filter(r => r.id !== confirmDeleteId.value)
    toast.add({ severity: 'success', summary: 'Deleted', detail: deleteTargetName.value, life: 3000 })
    deleteDialogVisible.value = false
  } catch (e) {
    const msg = e?.response?.data?.error ?? e.message
    toast.add({ severity: 'error', summary: 'Cannot delete', detail: msg, life: 5000 })
  } finally {
    deleting.value = false
  }
}

// ---- Bulk delete ----
const bulkDialogVisible = ref(false)
const bulkDeleting = ref(false)

const openBulkDelete = () => { bulkDialogVisible.value = true }

const confirmBulkDelete = async () => {
  bulkDeleting.value = true
  const ids = selection.value.map(r => r.id)
  let failed = 0
  for (const id of ids) {
    try {
      await segmentationConfigsAPI.delete(id)
      rows.value = rows.value.filter(r => r.id !== id)
    } catch {
      failed++
    }
  }
  if (failed) toast.add({ severity: 'warn', summary: 'Partial delete', detail: `${failed} config(s) could not be deleted (in use)`, life: 5000 })
  else toast.add({ severity: 'success', summary: 'Deleted', detail: `${ids.length} config(s) removed`, life: 3000 })
  selection.value = []
  bulkDialogVisible.value = false
  bulkDeleting.value = false
}
</script>

<template>
  <div class="p-4">
    <!-- Header -->
    <div class="flex align-items-center justify-content-between mb-4 gap-3">
      <div>
        <h2 class="text-2xl font-semibold m-0">Segmentation Configs</h2>
        <p class="text-sm text-color-secondary m-0 mt-1">
          Reusable portfolio segmentation rules — sector splits by subsector or country, ranked by EAD.
        </p>
      </div>
      <div class="flex gap-2">
        <Button
          v-if="selection.length > 0"
          label="Delete selected"
          icon="pi pi-trash"
          severity="danger"
          outlined
          size="small"
          @click="openBulkDelete"
        />
        <Button label="New Config" icon="pi pi-plus" size="small" @click="openCreate" />
      </div>
    </div>

    <!-- Toolbar -->
    <div class="flex align-items-center gap-2 mb-3">
      <span class="p-input-icon-left flex-1">
        <i class="pi pi-search" />
        <InputText v-model="filters.global.value" placeholder="Search configs…" class="w-full" />
      </span>
    </div>

    <!-- Table -->
    <DataTable
      v-model:selection="selection"
      :value="filteredRows"
      :loading="loading"
      paginator
      :rows="20"
      dataKey="id"
      responsiveLayout="scroll"
      class="p-datatable-sm"
    >
      <Column selectionMode="multiple" style="width: 3rem" />
      <Column field="name" header="Name" sortable>
        <template #body="{ data }">
          <span class="font-semibold">{{ data.name }}</span>
          <div v-if="data.description" class="text-xs text-color-secondary mt-1">{{ data.description }}</div>
        </template>
      </Column>
      <Column field="default_split" header="Default Split" sortable style="width: 10rem">
        <template #body="{ data }">
          <Tag :value="data.default_split" severity="secondary" />
        </template>
      </Column>
      <Column field="max_segments" header="Max Segments" sortable style="width: 9rem" />
      <Column header="Sector Overrides" style="width: 10rem">
        <template #body="{ data }">
          <span v-if="!data.sector_rules?.length" class="text-xs text-color-secondary">—</span>
          <span v-else class="text-xs">{{ data.sector_rules.length }} rule{{ data.sector_rules.length === 1 ? '' : 's' }}</span>
        </template>
      </Column>
      <Column field="created_by" header="Created By" style="width: 10rem" />
      <Column field="created_at" header="Created" sortable style="width: 10rem">
        <template #body="{ data }">{{ fmtDate(data.created_at) }}</template>
      </Column>
      <Column header="" style="width: 6rem; text-align: right">
        <template #body="{ data }">
          <div class="flex justify-content-end gap-1">
            <Button icon="pi pi-pencil" text rounded size="small" v-tooltip.top="'Edit'" @click="openEdit(data)" />
            <Button icon="pi pi-trash" text rounded size="small" severity="danger" v-tooltip.top="'Delete'" @click="openDelete(data)" />
          </div>
        </template>
      </Column>
      <template #empty>
        <div class="text-center p-4 text-color-secondary">
          No segmentation configs yet — click <b>New Config</b> to create one.
        </div>
      </template>
    </DataTable>

    <!-- Create / Edit dialog -->
    <Dialog
      v-model:visible="dialogVisible"
      :header="editingId ? 'Edit Segmentation Config' : 'New Segmentation Config'"
      modal
      :style="{ width: '42rem' }"
      :closable="!saving"
    >
      <div class="flex flex-column gap-4">
        <!-- Name -->
        <div class="flex flex-column gap-1">
          <label class="text-sm font-semibold">Name <span class="text-red-500">*</span></label>
          <InputText v-model="form.name" placeholder="e.g. Corporate Standard" class="w-full" />
        </div>

        <!-- Description -->
        <div class="flex flex-column gap-1">
          <label class="text-sm font-semibold">Description</label>
          <Textarea v-model="form.description" rows="2" class="w-full" placeholder="Optional notes" autoResize />
        </div>

        <!-- Default split + Max segments -->
        <div class="flex gap-3">
          <div class="flex flex-column gap-1 flex-1">
            <label class="text-sm font-semibold">Default Split</label>
            <div class="flex gap-2">
              <Button
                v-for="opt in SPLIT_OPTIONS"
                :key="opt.value"
                :label="opt.label"
                size="small"
                :severity="form.default_split === opt.value ? 'primary' : 'secondary'"
                :outlined="form.default_split !== opt.value"
                @click="form.default_split = opt.value"
              />
            </div>
          </div>
          <div class="flex flex-column gap-1" style="width: 9rem">
            <label class="text-sm font-semibold">Max Segments</label>
            <InputNumber v-model="form.max_segments" :min="2" :max="20" showButtons buttonLayout="horizontal" class="w-full" />
          </div>
        </div>

        <!-- Per-sector overrides -->
        <div class="flex flex-column gap-2">
          <div class="flex align-items-center justify-content-between">
            <label class="text-sm font-semibold">Sector Overrides</label>
            <Button label="Add override" icon="pi pi-plus" text size="small" @click="addSectorRule" />
          </div>
          <div v-if="form.sector_rules.length === 0" class="text-xs text-color-secondary">
            No overrides — all sectors use the default split above.
          </div>
          <div
            v-for="(rule, idx) in form.sector_rules"
            :key="idx"
            class="flex align-items-center gap-2 surface-ground border-round p-2"
          >
            <InputText v-model="rule.sector" placeholder="Sector name" class="flex-1" size="small" />
            <Dropdown
              v-model="rule.split_by"
              :options="SPLIT_OPTIONS"
              optionLabel="label"
              optionValue="value"
              class="w-8rem"
            />
            <InputNumber v-model="rule.max_segments" :min="2" :max="20" showButtons buttonLayout="horizontal" style="width: 7rem" />
            <Button icon="pi pi-times" text rounded severity="danger" size="small" @click="removeSectorRule(idx)" />
          </div>
        </div>
      </div>

      <template #footer>
        <Button label="Cancel" severity="secondary" text :disabled="saving" @click="dialogVisible = false" />
        <Button label="Save" icon="pi pi-check" :loading="saving" @click="saveDialog" />
      </template>
    </Dialog>

    <!-- Delete confirmation -->
    <ConfirmDialog />
    <Dialog
      v-model:visible="deleteDialogVisible"
      header="Delete Config"
      modal
      :style="{ width: '28rem' }"
      :closable="!deleting"
    >
      <p>Delete <b>{{ deleteTargetName }}</b>? This cannot be undone. Calibration runs using this config will be unaffected.</p>
      <template #footer>
        <Button label="Cancel" severity="secondary" text :disabled="deleting" @click="deleteDialogVisible = false" />
        <Button label="Delete" icon="pi pi-trash" severity="danger" :loading="deleting" @click="confirmDelete" />
      </template>
    </Dialog>

    <!-- Bulk delete confirmation -->
    <Dialog
      v-model:visible="bulkDialogVisible"
      header="Delete Selected"
      modal
      :style="{ width: '28rem' }"
      :closable="!bulkDeleting"
    >
      <p>Delete <b>{{ selection.length }}</b> segmentation config(s)? Configs currently referenced by calibration runs will be skipped.</p>
      <template #footer>
        <Button label="Cancel" severity="secondary" text :disabled="bulkDeleting" @click="bulkDialogVisible = false" />
        <Button label="Delete" icon="pi pi-trash" severity="danger" :loading="bulkDeleting" @click="confirmBulkDelete" />
      </template>
    </Dialog>
  </div>
</template>
