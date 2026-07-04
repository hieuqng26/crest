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

const initials = computed(() => {
  const email = user.value?.email || ''
  const name = email.split('@')[0] || ''
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
      <svg class="logo-beam" viewBox="0 0 62 7" xmlns="http://www.w3.org/2000/svg">
        <polygon points="0,7 62,0 62,3.4 0,7" fill="#FFE600" />
      </svg>
      <span class="brand-name">{{ appName }}</span>
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
      <span class="prod-badge">PROD</span>

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
        <span class="user-email">{{ user?.email }}</span>
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
  align-items: center;
}

.logo-beam {
  width: 32px;
  height: auto;
  margin-right: 0.625rem;
  flex-shrink: 0;
}

.brand-name {
  font-size: 1rem;
  font-weight: 800;
  letter-spacing: 0.18em;
  color: var(--chrome-text);
}

.brand-divider {
  width: 1px;
  align-self: stretch;
  margin: 0 0.875rem;
  background: var(--chrome-border);
}

.brand-tagline {
  font-size: 0.65625rem;
  line-height: 1.3;
  color: var(--chrome-text-muted);
  letter-spacing: 0.01em;
}

.prod-badge {
  display: inline-flex;
  align-items: center;
  height: 1.375rem;
  padding: 0 0.5rem;
  margin-right: 0.75rem;
  font-size: 0.65625rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--yellow);
  border: 1px solid var(--chrome-border);
}

.user-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 0.25rem 0.375rem;
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
  background: var(--yellow);
  color: var(--ink);
  font-size: 0.6875rem;
  font-weight: 700;
  font-family: 'IBM Plex Mono', monospace;
}

.user-email {
  font-size: 0.8125rem;
  color: var(--chrome-item-text);
}

@media (max-width: 991px) {
  .brand-tagline {
    display: none;
  }
}
</style>
