<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useLayout } from '@/layout/composables/layout'
import { useStore } from 'vuex'
import { useToast } from 'primevue/usetoast'
import router from '@/router'

defineProps({
  simple: {
    type: Boolean,
    default: false
  }
})

const store = useStore()
const toast = useToast()
const currentUser = store.getters.getCurrentUser
const user = ref(currentUser)

const appName = import.meta.env.VITE_APP_NAME || 'CREST'

const { onMenuToggle } = useLayout()

const outsideClickListener = ref(null)
const topbarMenuActive = ref(false)

const username = computed(() => (user.value?.email || '').split('@')[0] || '')

const initials = computed(() => {
  const name = username.value
  const parts = name.split(/[._-]/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return name.slice(0, 2).toUpperCase() || '—'
})

onMounted(() => {
  bindOutsideClickListener()
})

onBeforeUnmount(() => {
  unbindOutsideClickListener()
})

const onTopBarMenuButton = () => {
  topbarMenuActive.value = !topbarMenuActive.value
}

const topbarMenuClasses = computed(() => {
  return {
    'layout-topbar-menu-mobile-active': topbarMenuActive.value
  }
})

const bindOutsideClickListener = () => {
  if (!outsideClickListener.value) {
    outsideClickListener.value = (event) => {
      if (isOutsideClicked(event)) {
        topbarMenuActive.value = false
      }
    }
    document.addEventListener('click', outsideClickListener.value)
  }
}
const unbindOutsideClickListener = () => {
  if (outsideClickListener.value) {
    document.removeEventListener('click', outsideClickListener)
    outsideClickListener.value = null
  }
}
const isOutsideClicked = (event) => {
  if (!topbarMenuActive.value) return

  const sidebarEl = document.querySelector('.layout-topbar-menu')
  const topbarEl = document.querySelector('.layout-topbar-menu-button')
  return (
    sidebarEl &&
    !sidebarEl.isSameNode(event.target) &&
    !sidebarEl.contains(event.target) &&
    topbarEl &&
    !topbarEl.isSameNode(event.target) &&
    !topbarEl.contains(event.target)
  )
}

const logout = () => {
  sessionStorage.clear() // Clear client session
  store.dispatch('logout') // Clear server session
  router.push({ name: 'login' })
}

// update user
const showUpdateDialog = ref(false)

const updateUser = () => {
  if (user?.value.email?.trim()) {
    // Update user in db
    store
      .dispatch('updateUser', {
        userId: user.value.email,
        userData: {
          email: user.value.email,
          password: user.value.password
        }
      })
      .then((res) => {
        user.value = res.data

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

    showUpdateDialog.value = false
  }
}

// menu toggle
const menu = ref()
const items = ref([
  {
    items: [
      {
        label: 'Change password',
        icon: 'pi pi-id-card',
        command: () => {
          showUpdateDialog.value = true
        }
      },
      {
        label: 'Log out',
        icon: 'pi pi-sign-out',
        command: () => {
          logout()
        }
      }
    ]
  }
])

const toggleMenu = (event) => {
  menu.value.toggle(event)
}
</script>

<template>
  <div class="layout-topbar">
    <router-link to="/" class="layout-topbar-logo">
      <div class="logo-lockup">
        <svg class="logo-beam" viewBox="0 0 62 7" xmlns="http://www.w3.org/2000/svg">
          <polygon points="0,7 62,0 62,3.4 0,7" fill="#FFE600" />
        </svg>
        <span class="brand-name">{{ appName }}</span>
      </div>
      <div class="brand-divider" />
      <span class="brand-tagline">Credit Risk &amp;<br />Economic Stress Testing</span>
    </router-link>

    <button
      class="p-link layout-menu-button layout-topbar-button"
      @click="onMenuToggle()"
    >
      <i class="pi pi-bars"></i>
    </button>

    <button
      class="p-link layout-topbar-menu-button layout-topbar-button"
      @click="onTopBarMenuButton()"
    >
      <i class="pi pi-ellipsis-v"></i>
    </button>
    <div class="layout-topbar-menu" :class="topbarMenuClasses">
      <router-link
        v-if="!store.getters.isAuthenticated"
        to="/auth/login"
        class="layout-topbar-button"
      >
        <i class="pi pi-sign-in"></i>
      </router-link>
      <button
        v-if="store.getters.isAuthenticated"
        class="p-link user-chip"
        @click="toggleMenu"
      >
        <span class="user-avatar">{{ initials }}</span>
        <span class="user-email">{{ username }}</span>
      </button>
      <Menu ref="menu" id="overlay_menu" :model="items" :popup="true" />
    </div>

    <Dialog
      v-model:visible="showUpdateDialog"
      :style="{ width: '450px' }"
      header="Update Password"
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
        <label for="password" class="block text-900 text-l font-medium mb-2"
          >New Password</label
        >
        <Password
          id="password"
          v-model="user.password"
          :toggleMask="true"
          :feedback="true"
        >
        </Password>
      </div>

      <template #footer>
        <Button
          label="Cancel"
          icon="pi pi-times"
          text
          @click="showUpdateDialog = !showUpdateDialog"
        />
        <Button label="Save" icon="pi pi-check" text @click="updateUser" />
      </template>
    </Dialog>
  </div>
</template>

<style lang="scss" scoped>
.layout-topbar-logo {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.logo-lockup {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.logo-beam {
  width: 62px;
  height: 7px;
  display: block;
}

.brand-name {
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0.18em;
  line-height: 1;
  color: var(--chrome-text);
}

.brand-divider {
  width: 1px;
  height: 24px;
  margin: 0 2px;
  background: var(--chrome-border);
}

.brand-tagline {
  font-size: 10.5px;
  line-height: 1.3;
  color: var(--chrome-text-muted);
  letter-spacing: 0.02em;
  padding-bottom: 2px;
}

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  transition: background-color 0.15s ease;

  &:hover {
    background-color: var(--chrome-hover);
  }
}

.user-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  background: var(--yellow);
  color: var(--ink);
  font-size: 12px;
  font-weight: 700;
}

.user-email {
  font-size: 13px;
  color: #E7E7EA;
}

@media (max-width: 991px) {
  .brand-tagline {
    display: none;
  }
}
</style>
