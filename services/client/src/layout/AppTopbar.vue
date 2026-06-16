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

const appName = import.meta.env.VITE_APP_NAME

const { onMenuToggle } = useLayout()

const logoUrl = '/layout/images/logo-ey.svg'
const outsideClickListener = ref(null)
const topbarMenuActive = ref(false)

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
    // label: 'Options',
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
      <img :src="logoUrl" alt="logo" />
      <div class="brand-text">
        <span class="brand-name">{{ appName }}</span>
        <span class="brand-tagline">Credit Risk &amp; Economic Stress Testing</span>
      </div>
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
        class="p-link layout-topbar-button"
        @click="toggleMenu"
      >
        <i class="pi pi-user"></i>
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
.brand-text {
  display: flex;
  flex-direction: column;
  margin-left: 0.625rem;
  line-height: 1.15;
}
.brand-name {
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--text-color);
}
.brand-tagline {
  font-size: 0.6875rem;
  color: var(--text-color-secondary);
  letter-spacing: 0.02em;
}

.notification-button {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  position: relative;
  color: var(--text-color-secondary);
  border-radius: 50%;
  width: 3rem;
  height: 3rem;
  cursor: pointer;
  transition: background-color 0.2s;
  background-color: var(--surface-card);
  border-width: 0px;
  &:hover {
    color: var(--text-color);
    background-color: var(--surface-hover);
  }

  i {
    font-size: 1.5rem;
  }
}

@media (max-width: 991px) {
  .notification-button {
    margin-left: 0;
    display: flex;
    width: 100%;
    height: auto;
    justify-content: flex-start;
    border-radius: 12px;
    padding: 1rem;

    i {
      font-size: 1rem;
      margin-right: 0.5rem;
    }

    span {
      font-weight: medium;
      display: block;
    }
  }
}
</style>
