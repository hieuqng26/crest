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
        <svg class="logo-beam" viewBox="0 0 78 9" xmlns="http://www.w3.org/2000/svg">
          <polygon points="0,9 78,0 78,4.2 0,9" fill="#FFE600" />
        </svg>
        <span class="login-brand-name">{{ appName }}</span>
      </router-link>

      <div class="login-left-center">
        <div class="login-yellow-bar" />
        <h1 class="login-headline">Credit Risk &amp; Economic Stress Testing</h1>
        <p class="login-support">
          Calibrate models, forecast macro scenarios, and quantify expected
          credit losses across your portfolio.
        </p>
      </div>

      <div class="login-left-bottom">
        <span class="login-footnote">EY &middot; &copy; 2026</span>
      </div>
    </div>

    <div class="login-right">
      <div class="login-card card--emphasis">
        <h2 class="login-heading">Sign in</h2>
        <p class="login-subtitle">Use your organisation account</p>

        <div class="login-field-email">
          <label for="email" class="login-label">Email</label>
          <InputText
            id="email"
            v-model="email"
            type="text"
            placeholder="name@bank.com"
            class="w-full login-input"
            autocomplete="username"
            @keyup.enter="login"
          />
        </div>

        <div class="login-field-password">
          <div class="login-row-label">
            <label for="password" class="login-label login-label--inline">Password</label>
            <a class="login-forgot-link" @click="notConfigured('Password reset')">Forgot?</a>
          </div>
          <Password
            id="password"
            v-model="password"
            placeholder="••••••••"
            :toggleMask="true"
            :feedback="false"
            class="w-full"
            inputClass="w-full login-input"
            autocomplete="current-password"
            @keyup.enter="login"
          />
        </div>

        <Button label="Sign in" class="w-full login-btn btn-cta" @click="login" />

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
  padding: 48px 52px;
}

.login-logo-lockup {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.logo-beam {
  width: 78px;
  height: 9px;
  display: block;
}
.login-brand-name {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.18em;
  line-height: 1;
  color: #fff;
}

.login-left-center {
  max-width: 420px;
}
.login-yellow-bar {
  width: 48px;
  height: 4px;
  background: var(--yellow);
  margin-bottom: 22px;
}
.login-headline {
  font-size: 34px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.01em;
  color: #fff;
  margin: 0;
  max-width: 420px;
}
.login-support {
  font-size: 14px;
  line-height: 1.6;
  color: var(--chrome-text-muted);
  margin: 16px 0 0;
  max-width: 400px;
}

.login-left-bottom {
  display: flex;
  align-items: center;
}
.login-footnote {
  font-size: 12px;
  color: #5A5A66;
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
  width: 400px;
  padding: 36px 40px 40px;
}

.login-heading {
  margin: 0 0 4px;
  font-size: 21px;
  font-weight: 700;
  color: var(--text-color);
}
.login-subtitle {
  margin: 0 0 26px;
  font-size: 13px;
  color: var(--text-color-muted);
}

.login-field-email {
  margin-bottom: 16px;
}
.login-field-password {
  margin-bottom: 24px;
}
.login-label {
  display: block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-color-muted);
  margin-bottom: 6px;
}
.login-row-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 6px;
}
.login-row-label .login-label--inline {
  margin-bottom: 0;
}
:deep(.login-input) {
  height: 42px;
  font-size: 13.5px;
}

.login-forgot-link {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-color-secondary);
  cursor: pointer;
  border-bottom: 2px solid var(--yellow);
  padding-bottom: 1px;
  transition: color 0.15s ease;
}
.login-forgot-link:hover {
  color: var(--ink);
}

.login-btn {
  height: 44px;
  font-size: 14px;
}

.login-divider-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0;
}
.login-divider-line {
  flex: 1;
  height: 1px;
  background: var(--surface-border-row);
}
.login-divider-text {
  font-size: 11px;
  color: var(--text-color-muted-2);
}

.login-sso-btn {
  height: 44px;
  font-size: 13.5px;
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
    padding: 24px;
  }
  .login-left-center {
    margin: 32px 0;
  }
}
</style>
