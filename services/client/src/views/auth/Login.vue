<script setup>
import { ref, onMounted } from 'vue'
import router from '@/router'
import { useToast } from 'primevue/usetoast'
import { useStore } from 'vuex'
import { useRoute } from 'vue-router'

const logoUrl = '/layout/images/logo-ey-dark.svg'
const appName = import.meta.env.VITE_APP_NAME
const store = useStore()
const toast = useToast()

const email    = ref('')
const password = ref('')

const route = useRoute()
onMounted(() => {
  if (route.query?.errorMessage) {
    toast.add({ severity: 'error', summary: 'Error', detail: route.query?.errorMessage, life: 5000 })
  }
})

const login = async () => {
  if (!email.value || !password.value) {
    toast.add({ severity: 'error', summary: 'Error', detail: 'User ID and Password are required', life: 3000 })
    return
  }
  await store
    .dispatch('login', { email: email.value, password: password.value })
    .then(() => router.push({ name: 'dashboard' }))
    .catch((err) => {
      const msg = err.response?.data?.message || err.message
      toast.add({ severity: 'error', summary: 'Error', detail: msg, life: 5000 })
    })
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">

      <!-- Branding -->
      <div class="login-brand">
        <img :src="logoUrl" alt="EY logo" class="login-logo" />
        <div class="login-brand-text">
          <span class="login-app-name">{{ appName }}</span>
          <span class="login-app-tagline">Credit Risk &amp; Economic Stress Testing</span>
        </div>
      </div>

      <div class="login-divider" />

      <h2 class="login-heading">Sign in</h2>

      <!-- Fields -->
      <div class="login-field">
        <label for="email">User ID</label>
        <InputText
          id="email"
          v-model="email"
          type="text"
          placeholder="Enter your user ID"
          class="w-full"
          autocomplete="username"
          @keyup.enter="login"
        />
      </div>

      <div class="login-field">
        <label for="password">Password</label>
        <Password
          id="password"
          v-model="password"
          placeholder="Enter your password"
          :toggleMask="true"
          :feedback="false"
          class="w-full"
          inputClass="w-full"
          autocomplete="current-password"
          @keyup.enter="login"
        />
      </div>

      <Button label="Sign In" class="w-full login-btn" @click="login" />
    </div>

    <Toast />
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-ground);
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 2.5rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: var(--radius-lg);
}

/* Branding row */
.login-brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1.75rem;
}
.login-logo {
  height: 2rem;
  flex-shrink: 0;
}
.login-brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.login-app-name {
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--text-color);
}
.login-app-tagline {
  font-size: 0.6875rem;
  color: var(--text-color-secondary);
  letter-spacing: 0.02em;
}

.login-divider {
  height: 1px;
  background: var(--surface-border);
  margin-bottom: 1.75rem;
}

.login-heading {
  margin: 0 0 1.5rem;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-color);
  letter-spacing: -0.01em;
}

.login-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 1.1rem;
}
.login-field label {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-color-secondary);
}

.login-btn {
  margin-top: 0.75rem;
  height: 2.75rem;
  font-size: 0.9375rem;
}

/* Password component full width */
:deep(.p-password) { width: 100%; }
:deep(.p-password-input) { width: 100%; }
</style>
