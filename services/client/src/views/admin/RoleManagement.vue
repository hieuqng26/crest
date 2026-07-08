<!-- services/client/src/views/admin/RoleManagement.vue -->
<template>
  <div>
    <PageHeader eyebrow="SYSTEM" title="Role Management" subtitle="Define roles and the pages each role can read, write, or execute.">
      <template #actions>
        <Button v-can="'role:write'" icon="pi pi-plus" label="New Role" @click="openCreate" />
      </template>
    </PageHeader>

    <div class="panel">
      <DataTable :value="roles" dataKey="name" class="bare-table-inner">
        <Column field="name" header="Role" sortable style="min-width: 12rem">
          <template #body="{ data }">
            <span class="font-medium">{{ data.name }}</span>
            <Tag v-if="data.is_system" value="built-in" severity="warning" class="ml-2" />
          </template>
        </Column>
        <Column field="description" header="Description" style="min-width: 18rem" />
        <Column field="user_count" header="Users" style="width: 7rem" />
        <Column :exportable="false" style="width: 9rem">
          <template #body="{ data }">
            <div class="flex gap-1 justify-content-end">
              <Button icon="pi pi-pencil" text rounded size="small" severity="secondary" v-tooltip.top="'Edit role'" aria-label="Edit role"
                      :disabled="data.is_system || !canWrite" @click="openEdit(data)" />
              <Button icon="pi pi-trash" text rounded size="small" severity="danger" v-tooltip.top="'Delete role'" aria-label="Delete role"
                      :disabled="data.is_system || !canWrite" @click="confirmDelete(data)" />
            </div>
          </template>
        </Column>
      </DataTable>
    </div>

    <Dialog v-model:visible="showDialog" :style="{ width: '640px' }" :header="editing ? 'Edit Role' : 'New Role'" modal class="p-fluid">
      <div class="field">
        <label class="block text-900 font-medium mb-2">Name</label>
        <InputText v-model.trim="form.name" :disabled="editing" placeholder="e.g. risk_lead" />
        <small class="text-color-secondary">Lowercase letters, digits, underscores.</small>
      </div>
      <div class="field">
        <label class="block text-900 font-medium mb-2">Description</label>
        <InputText v-model.trim="form.description" />
      </div>

      <label class="block text-900 font-medium mb-2">Permissions</label>
      <table class="perm-matrix">
        <thead>
          <tr><th>Page</th><th>Read</th><th>Write</th><th>Execute</th></tr>
        </thead>
        <tbody>
          <tr v-for="page in catalog" :key="page.key">
            <td>{{ page.label }}</td>
            <td v-for="action in ['read','write','execute']" :key="action">
              <Checkbox v-if="hasAction(page, action)" :binary="true"
                        :modelValue="isChecked(page.key, action)"
                        @update:modelValue="(v) => toggle(page.key, action, v)" />
              <span v-else class="text-color-secondary">—</span>
            </td>
          </tr>
        </tbody>
      </table>

      <template #footer>
        <Button label="Cancel" icon="pi pi-times" text @click="showDialog = false" />
        <Button label="Save" icon="pi pi-check" text @click="save" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useStore } from 'vuex'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import { roleAPI } from '@/api'
import PageHeader from '@/components/ui/PageHeader.vue'

const store = useStore()
const toast = useToast()
const confirm = useConfirm()

const roles = ref([])
const catalog = ref([])
const showDialog = ref(false)
const editing = ref(false)
const form = reactive({ name: '', description: '', permissions: new Set() })

const canWrite = computed(() => store.getters.can('role:write'))

const load = async () => {
  const [r, c] = await Promise.all([roleAPI.list(), roleAPI.catalog()])
  roles.value = r.data
  catalog.value = c.data.pages
}

onMounted(load)

const hasAction = (page, action) => page.actions.some((a) => a.key === action)
const isChecked = (pageKey, action) => form.permissions.has(`${pageKey}:${action}`)
const toggle = (pageKey, action, value) => {
  const key = `${pageKey}:${action}`
  if (value) form.permissions.add(key)
  else form.permissions.delete(key)
}

const openCreate = () => {
  editing.value = false
  form.name = ''; form.description = ''; form.permissions = new Set()
  showDialog.value = true
}
const openEdit = (role) => {
  editing.value = true
  form.name = role.name; form.description = role.description || ''
  form.permissions = new Set(role.permissions)
  showDialog.value = true
}

const save = async () => {
  const payload = { name: form.name, description: form.description, permissions: [...form.permissions] }
  try {
    if (editing.value) await roleAPI.update(form.name, { description: payload.description, permissions: payload.permissions })
    else await roleAPI.create(payload)
    showDialog.value = false
    await load()
    toast.add({ severity: 'success', summary: 'Saved', detail: `Role ${form.name} saved.`, life: 2500 })
  } catch (err) {
    toast.add({ severity: 'error', summary: 'Error', detail: err.response?.data?.message || err.message, life: 5000 })
  }
}

const confirmDelete = (role) => {
  confirm.require({
    message: `Delete role "${role.name}"?`,
    header: 'Confirm',
    icon: 'pi pi-exclamation-triangle',
    accept: async () => {
      try {
        await roleAPI.remove(role.name)
        await load()
        toast.add({ severity: 'info', summary: 'Deleted', detail: `Role ${role.name} deleted.`, life: 2500 })
      } catch (err) {
        toast.add({ severity: 'error', summary: 'Error', detail: err.response?.data?.message || err.message, life: 6000 })
      }
    }
  })
}
</script>

<style scoped>
.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 2px; padding: 1.25rem; }
.perm-matrix { width: 100%; border-collapse: collapse; }
.perm-matrix th {
  text-align: left;
  padding: 0.5rem 0.75rem;
  border-bottom: 2px solid var(--ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-color-muted);
}
.perm-matrix td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--surface-border-row); font-size: 13px; }
.perm-matrix th:not(:first-child), .perm-matrix td:not(:first-child) { text-align: center; width: 5rem; }
</style>
