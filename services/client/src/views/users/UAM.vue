<template>
  <div class="p-5 mx-auto" style="max-width: 1400px">
    <!-- Page header -->
    <header class="flex align-items-end justify-content-between mb-5 flex-wrap gap-3">
      <div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">User Access Management</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">Manage platform users and their roles.</p>
      </div>
      <div class="flex align-items-center gap-2">
        <input ref="fileInput" type="file" accept=".csv,.xlsx,.xls" style="display:none" @change="onFileChange" />
        <Button icon="pi pi-upload" label="Import" text class="action-btn" @click="fileInput.click()" />
        <Button icon="pi pi-download" label="Export" text class="action-btn" @click="exportMenu.toggle($event)" />
        <Menu ref="exportMenu" :model="exportOptions" popup :pt="{ label: { style: 'font-size:0.7rem' }, icon: { style: 'font-size:0.7rem' } }" />
      </div>
    </header>

    <!-- Users table -->
    <div class="panel">
      <div class="bare-table">
        <DataTable
          ref="dt"
          :value="users"
          dataKey="id"
          :paginator="true"
          :rows="20"
          :filters="filters"
          removableSort
          paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
          :rowsPerPageOptions="[10, 20, 50]"
          currentPageReportTemplate="Showing {first} to {last} of {totalRecords} users"
          class="bare-table-inner"
        >
          <template #header>
            <div class="flex align-items-center justify-content-between pb-2">
              <span class="panel-section-label">Users</span>
              <IconField iconPosition="left">
                <InputIcon><i class="pi pi-search" /></InputIcon>
                <InputText v-model="filters['global'].value" placeholder="Search…" />
              </IconField>
            </div>
          </template>

          <Column field="email"         header="Email"           sortable style="min-width: 14rem" />
          <Column field="name"          header="Name"            sortable style="min-width: 12rem" />
          <Column field="role"          header="Role"            sortable style="min-width: 8rem" />
          <Column field="registered_on" header="Registered"      sortable style="min-width: 10rem">
            <template #body="{ data }">{{ formatDate(data.registered_on) }}</template>
          </Column>
          <Column field="status"        header="Status"          sortable style="min-width: 8rem">
            <template #body="{ data }">
              <Tag :value="data.status" :severity="getStatusLabel(data.status)" />
            </template>
          </Column>
          <Column :exportable="false" style="width: 7rem">
            <template #body="{ data }">
              <div class="flex gap-1 justify-content-end">
                <Button icon="pi pi-pencil" text rounded size="small" severity="secondary" @click="onUpdateUser(data)" />
                <Button icon="pi pi-trash"  text rounded size="small" severity="danger"    @click="onDeleteUser(data)" />
              </div>
            </template>
          </Column>
        </DataTable>
      </div>
  </div>

    <Dialog
      v-model:visible="showAddDialog"
      :style="{ width: '450px' }"
      header="Add User"
      :modal="true"
      class="p-fluid"
    >
      <div class="field">
        <label for="email" class="block text-900 text-l font-medium mb-2"
          >Email</label
        >
        <InputText
          id="email"
          v-model.trim="user.email"
          required="true"
          autofocus
          :invalid="addSubmitted && !user.email"
        />
        <small class="p-error" v-if="addSubmitted && !user.email"
          >Email is required.</small
        >
      </div>

      <div class="field">
        <label for="password" class="block text-900 text-l font-medium mb-2"
          >Password</label
        >
        <Password
          id="password"
          v-model="user.password"
          :toggleMask="true"
          :feedback="true"
          :invalid="addSubmitted && !user.password"
          :required="true"
        >
        </Password>
        <small class="p-error" v-if="addSubmitted && !user.password"
          >Password is required.</small
        >
      </div>

      <div class="field">
        <label for="name" class="block text-900 text-l font-medium mb-2"
          >Name</label
        >
        <InputText id="name" v-model.trim="user.name" />
      </div>

      <div class="field">
        <label for="role" class="block text-900 text-l font-medium mb-2"
          >Role</label
        >
        <Dropdown id="role" v-model.trim="user.role" :options="roles" />
      </div>

      <div class="field">
        <label for="registeredOn" class="block text-900 text-l font-medium mb-2"
          >Registered On</label
        >
        <Calendar
          id="registeredOn"
          v-model="user.registered_on"
          dateFormat="yy-mm-dd"
        />
      </div>

      <div class="field">
        <label for="status" class="block text-900 text-l font-medium mb-2"
          >Status</label
        >
        <SelectButton
          id="status"
          v-model.trim="user.status"
          :options="['active', 'inactive']"
          aria-labelledby="basic"
        />
      </div>

      <template #footer>
        <Button label="Cancel" icon="pi pi-times" text @click="hideAddDialog" />
        <Button label="Save" icon="pi pi-check" text @click="addUser" />
      </template>
    </Dialog>

    <Dialog
      v-model:visible="showUpdateDialog"
      :style="{ width: '450px' }"
      header="Update User"
      :modal="true"
      class="p-fluid"
    >
      <div class="field">
        <label for="email" class="block text-900 text-l font-medium mb-2"
          >Email</label
        >
        <InputText
          id="email"
          v-model.trim="user.email"
          required="true"
          autofocus
          disabled
        />
      </div>

      <div class="field">
        <label for="name" class="block text-900 text-l font-medium mb-2"
          >Name</label
        >
        <InputText id="name" v-model.trim="user.name" />
      </div>

      <div class="field">
        <label for="password" class="block text-900 text-l font-medium mb-2"
          >Password</label
        >
        <Password
          id="password"
          v-model="user.password"
          :toggleMask="true"
          :feedback="true"
        >
        </Password>
      </div>

      <div class="field">
        <label for="role" class="block text-900 text-l font-medium mb-2"
          >Role</label
        >
        <Dropdown id="role" v-model.trim="user.role" :options="roles" />
      </div>

      <div class="field">
        <label for="registeredOn" class="block text-900 text-l font-medium mb-2"
          >Registered On</label
        >
        <Calendar
          id="registeredOn"
          v-model="user.registered_on"
          dateFormat="yy-mm-dd"
        />
      </div>

      <div class="field">
        <label for="status" class="block text-900 text-l font-medium mb-2"
          >Status</label
        >
        <SelectButton
          id="status"
          v-model.trim="user.status"
          :options="['active', 'inactive']"
          aria-labelledby="basic"
        />
      </div>

      <template #footer>
        <Button
          label="Cancel"
          icon="pi pi-times"
          text
          @click="hideUpdateDialog"
        />
        <Button label="Save" icon="pi pi-check" text @click="updateUser" />
      </template>
    </Dialog>

    <Dialog
      v-model:visible="showDeleteDialog"
      :style="{ width: '450px' }"
      header="Confirm"
      :modal="true"
    >
      <div class="confirmation-content">
        <i class="pi pi-exclamation-triangle mr-3" style="font-size: 2rem" />
        <span v-if="user"
          >Are you sure you want to delete <b>{{ user.name }}</b
          >?</span
        >
      </div>
      <template #footer>
        <Button
          label="No"
          icon="pi pi-times"
          text
          severity="secondary"
          @click="showDeleteDialog = false"
        />
        <Button
          label="Yes"
          icon="pi pi-check"
          text
          severity="danger"
          @click="deleteUser"
        />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { FilterMatchMode } from 'primevue/api'
import { useStore } from 'vuex'
import { useToast } from 'primevue/usetoast'
import { formatDate } from '@/utils'
import { saveFile } from '@/views/composables/views.js'

const store = useStore()
const toast = useToast()

// refs
const roles    = ref(null)
const dt       = ref()
const users    = ref()
const fileInput = ref()
const exportMenu = ref()
const loading  = ref(false)

const showAddDialog = ref(false)
const showUpdateDialog = ref(false)
const showDeleteDialog = ref(false)
const user = ref({})
const filters = ref({
  global: { value: null, matchMode: FilterMatchMode.CONTAINS }
})
const addSubmitted = ref(false) // to validate mandatory fields are filled
const updateSubmitted = ref(false) // to validate mandatory fields are filled

// properties
onMounted(() => {
  let forceLoadDB = true
  store.dispatch('getAllRolePermissions', forceLoadDB).then((res) => {
    roles.value = Object.keys(res)
  })
  store
    .dispatch('getAllUsers')
    .then((res) => {
      users.value = res.data
    })
    .catch((err) => {
      const msg = err.response?.data?.message || err.message
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: 'Failed to fetch users. ' + msg,
        life: 5000
      })
    })
})

const onFileChange = (event) => {
  const fileUp = event.target.files[0]
  if (!fileUp) return
  fileInput.value.value = ''

  const formData = new FormData()
  formData.append('file', fileUp)
  loading.value = true

  store
    .dispatch('uploadInputData', { formData: formData, id: 'users_upload' })
    .then(async (res) => {
      await store.dispatch('addMultiUsers', JSON.parse(res.data))
      store.dispatch('getAllUsers').then((res) => { users.value = res.data })
      loading.value = false
      toast.add({ severity: 'success', summary: 'Imported', detail: `${fileUp.name} uploaded.`, life: 2000 })
    })
    .catch((err) => {
      loading.value = false
      toast.add({ severity: 'error', summary: 'Error', detail: 'File not uploaded. ' + (err.response?.data?.message || err.message), life: 5000 })
    })
}

const exportOptions = [
  { label: 'CSV',  icon: 'pi pi-file',       command: () => saveFile(downloadData.value, 'csv',  'users') },
  { label: 'XLSX', icon: 'pi pi-file-excel',  command: () => saveFile(downloadData.value, 'xlsx', 'users') },
]

const hideAddDialog = () => {
  user.value = {}
  showAddDialog.value = false
  addSubmitted.value = false
}

const onAddUser = () => {
  user.value = {
    id: createId(),
    registered_on: new Date(),
    status: 'active',
    role: 'readonly'
  }
  addSubmitted.value = false
  showAddDialog.value = true
}

const addUser = () => {
  addSubmitted.value = true
  if (
    user?.value.email?.trim() &&
    (user?.value.status == 'active' || user?.value.status == 'inactive')
  ) {
    // Add user in db
    store
      .dispatch('addUser', {
        email: user.value.email,
        password: user.value.password,
        role: user.value.role,
        name: user.value.name,
        status: user.value.status,
        registeredOn: user.value.registered_on
      })
      .then((res) => {
        // Add user in data table
        users.value.push(res.data)

        hideAddDialog()
        toast.add({
          severity: 'success',
          summary: 'Success',
          detail: 'User added!',
          life: 3000
        })
      })
      .catch((err) => {
        const msg = err.response?.data?.message || err.message
        toast.add({
          severity: 'error',
          summary: 'Error',
          detail: 'Failed to add user. ' + msg,
          life: 5000
        })
      })
  }
}

const hideUpdateDialog = () => {
  user.value = {}
  showUpdateDialog.value = false
  updateSubmitted.value = false
}

const onUpdateUser = (rowData) => {
  user.value = JSON.parse(JSON.stringify(rowData))
  user.value.registered_on = new Date(rowData.registered_on)
  showUpdateDialog.value = true
}

const updateUser = () => {
  updateSubmitted.value = true

  if (user?.value.email?.trim()) {
    // Update user in db
    store
      .dispatch('updateUser', {
        userId: user.value.email,
        userData: {
          email: user.value.email,
          password: user.value.password,
          role: user.value.role,
          name: user.value.name,
          status: user.value.status,
          registeredOn: user.value.registered_on
        }
      })
      .then((res) => {
        let data = res.data
        data.registered_on = new Date(data.registered_on) // make sure the date is converted to local timezone
        users.value[findIndexByEmail(data.email)] = data

        hideUpdateDialog()
        toast.add({
          severity: 'success',
          summary: 'Success',
          detail: 'Update successfully!',
          life: 3000
        })
      })
      .catch((err) => {
        const msg = err.response?.data?.message || err.message
        toast.add({
          severity: 'error',
          summary: 'Error',
          detail: 'Update failed. ' + msg,
          life: 5000
        })
      })
  }
}

const hideDeleteDialog = () => {
  user.value = {}
  showDeleteDialog.value = false
}

const onDeleteUser = (rowData) => {
  user.value = rowData
  showDeleteDialog.value = true
}
const deleteUser = () => {
  // Delete user in db
  store
    .dispatch('deleteUser', user.value.email)
    .then((res) => {
      // Delete user in data table
      users.value = users.value.filter((val) => val.id !== user.value.id)

      hideDeleteDialog()
      toast.add({
        severity: 'info',
        summary: 'Confirmed',
        detail: 'User deleted!',
        life: 3000
      })
    })
    .catch((err) => {
      const msg = err.response?.data?.message || err.message
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: 'Failed to delete user. ' + msg,
        life: 5000
      })
    })
}

// helper functions
const findIndexByEmail = (email) => {
  let index = -1
  for (let i = 0; i < users.value.length; i++) {
    if (users.value[i].email === email) {
      index = i
      break
    }
  }

  return index
}
const createId = () => {
  let id = ''
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  const array = new Uint8Array(5)
  window.crypto.getRandomValues(array)
  for (const value of array) {
    id += chars.charAt(value % chars.length)
  }
  return id
}

const getStatusLabel = (status) => {
  switch (status) {
    case 'active':
      return 'success'

    case 'inactive':
      return 'secondary'

    default:
      return null
  }
}

const downloadData = computed(() => {
  if (users.value) {
    const data = JSON.parse(JSON.stringify(users.value))
    data.forEach((user) => {
      user.registered_on = formatDate(user.registered_on)
      user.password = null

      // remove id, last_login, and last_logout fields
      delete user.id
      delete user.last_login
      delete user.last_logout
    })

    return data
  }
})
</script>

<style scoped>
.panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  padding: 1.25rem 1.25rem 0;
}
.panel-section-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  color: var(--text-color-secondary);
}

.action-btn { color: var(--text-color-secondary) !important; font-size: 0.85rem; }
.action-btn:hover { color: var(--text-color) !important; background: var(--surface-hover) !important; }

.bare-table { margin: 0 -1.25rem; }
:deep(.bare-table-inner .p-datatable-thead > tr > th) {
  background: transparent;
  color: var(--text-color-secondary);
  font-weight: 500;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.6rem 1.25rem;
}
:deep(.bare-table-inner .p-datatable-tbody > tr > td) {
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  padding: 0.75rem 1.25rem;
  font-size: 0.875rem;
}
:deep(.bare-table-inner .p-datatable-tbody > tr:last-child > td) { border-bottom: 0; }
:deep(.bare-table-inner .p-datatable-header) {
  background: transparent;
  border: 0;
  padding: 0 1.25rem 0.75rem;
}
:deep(.bare-table-inner .p-paginator) {
  background: transparent;
  border: 0;
  border-top: 1px solid var(--surface-border);
  padding: 0.6rem 1.25rem;
}
</style>
