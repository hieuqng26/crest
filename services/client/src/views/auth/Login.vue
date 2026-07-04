<script setup>
import { ref, onMounted } from 'vue'
import router from '@/router'
import { useToast } from 'primevue/usetoast'
import { useStore } from 'vuex'
import { useRoute } from 'vue-router'

const appName = import.meta.env.VITE_APP_NAME || 'CREST'
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
    toast.add({ severity: 'error', summary: 'Error', detail: 'Email and password are required', life: 3000 })
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

const notConfigured = (feature) => {
  toast.add({ severity: 'info', summary: 'Not configured', detail: `${feature} is not set up for this deployment.`, life: 4000 })
}
</script>

<template>
  <div class="login-page">
    <div class="login-left">
      <router-link to="/auth/login" class="login-logo-lockup">
        <svg class="logo-beam" viewBox="0 0 62 7" xmlns="http://www.w3.org/2000/svg">
          <polygon points="0,7 62,0 62,3.4 0,7" fill="#FFE600" />
        </svg>
        <span class="login-brand-name">{{ appName }}</span>
      </router-link>

      <div class="login-left-center">
        <div class="login-yellow-bar" />
        <h1 class="login-headline">Credit Risk &amp; Economic Stress Testing</h1>
        <p class="login-support">
          ML-driven calibration, forecasting and IFRS 9 credit-risk analytics for
          banking-grade stress testing.
        </p>
      </div>

      <div class="login-left-bottom">
        <span class="prod-badge">PROD</span>
        <span class="login-footnote">Internal use only &middot; &copy; 2026</span>
      </div>
    </div>

    <div class="login-right">
      <div class="login-card card--emphasis">
        <h2 class="login-heading">Sign in</h2>

        <div class="login-field">
          <label for="email" class="login-label">Email</label>
          <InputText
            id="email"
            v-model="email"
            type="text"
            placeholder="you@bank.com"
            class="w-full login-input"
            autocomplete="username"
            @keyup.enter="login"
          />
        </div>

        <div class="login-field">
          <label for="password" class="login-label">Password</label>
          <Password
            id="password"
            v-model="password"
            placeholder="Enter your password"
            :toggleMask="true"
            :feedback="false"
            class="w-full"
            inputClass="w-full login-input"
            autocomplete="current-password"
            @keyup.enter="login"
          />
        </div>

        <div class="login-forgot-row">
          <a class="login-forgot-link" @click="notConfigured('Password reset')">Forgot?</a>
        </div>

        <Button label="Sign In" class="w-full login-btn" @click="login" />

        <div class="login-divider-row">
          <span class="login-divider-line" />
          <span class="login-divider-text">OR</span>
          <span class="login-divider-line" />
        </div>

        <Button
          label="Continue with SSO"
          outlined
          class="w-full login-sso-btn"
          @click="notConfigured('SSO')"
        />
      </div>
    </div>

    <Toast />
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
}

/* ── Left: ink brand panel ─────────────────────────────────────────── */
.login-left {
  flex: 0 0 42%;
  min-width: 380px;
  background: var(--ink);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 2rem 3rem;
}

.login-logo-lockup {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.logo-beam {
  width: 40px;
  height: auto;
}
.login-brand-name {
  font-size: 1.125rem;
  font-weight: 800;
  letter-spacing: 0.18em;
  color: #fff;
}

.login-left-center {
  max-width: 420px;
}
.login-yellow-bar {
  width: 48px;
  height: 4px;
  background: var(--yellow);
  margin-bottom: 1.25rem;
}
.login-headline {
  font-size: 2.125rem;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.01em;
  color: #fff;
  margin: 0 0 0.75rem;
}
.login-support {
  font-size: 0.875rem;
  line-height: 1.5;
  color: var(--chrome-text-muted);
  margin: 0;
}

.login-left-bottom {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}
.prod-badge {
  display: inline-flex;
  align-items: center;
  height: 1.375rem;
  padding: 0 0.5rem;
  font-size: 0.65625rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--yellow);
  border: 1px solid var(--chrome-border);
}
.login-footnote {
  font-size: 0.75rem;
  color: var(--chrome-text-muted);
}

/* ── Right: sign-in card ───────────────────────────────────────────── */
.login-right {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-ground);
  padding: 2rem;
}

.login-card {
  width: 100%;
  max-width: 400px;
  padding: 2rem 2.25rem 2.25rem;
}

.login-heading {
  margin: 0 0 1.5rem;
  font-size: 1.3125rem;
  font-weight: 700;
  color: var(--text-color);
  letter-spacing: -0.01em;
}

.login-field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 1.1rem;
}
.login-label {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-color-secondary);
}
:deep(.login-input) {
  height: 42px;
}

.login-forgot-row {
  display: flex;
  justify-content: flex-end;
  margin: -0.4rem 0 1rem;
}
.login-forgot-link {
  font-size: 0.8125rem;
  color: var(--text-color-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  padding-bottom: 1px;
  transition: border-color 0.15s ease, color 0.15s ease;
}
.login-forgot-link:hover {
  color: var(--text-color);
  border-bottom-color: var(--yellow);
}

.login-btn {
  height: 44px;
  font-size: 0.9375rem;
}

.login-divider-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin: 1.25rem 0;
}
.login-divider-line {
  flex: 1;
  height: 1px;
  background: var(--surface-border);
}
.login-divider-text {
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-color-muted-2);
}

.login-sso-btn {
  height: 42px;
}

/* Password component full width */
:deep(.p-password) { width: 100%; }
:deep(.p-password-input) { width: 100%; }

@media (max-width: 767px) {
  .login-page {
    flex-direction: column;
  }
  .login-left {
    flex: none;
    min-width: 0;
    padding: 1.5rem;
  }
  .login-left-center {
    margin: 2rem 0;
  }
}
</style>
