<script setup>
import { ref, onMounted } from 'vue'
import router from '@/router'
import { useToast } from 'primevue/usetoast'
import { useStore } from 'vuex'
import { useRoute } from 'vue-router'

const logoUrl = '/layout/images/logo-ey.svg'
const appName = import.meta.env.VITE_APP_NAME
const store = useStore()
const toast = useToast()

const email = ref('')
const password = ref('')

const route = useRoute()
onMounted(() => {
  if (route.query?.errorMessage) {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: route.query?.errorMessage,
      life: 5000
    })
  }
})

const login = async () => {
  if (!email.value || !password.value) {
    const message = 'User ID and/or Password are required'
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: message,
      life: 3000
    })
    return
  }

  await store
    .dispatch('login', {
      email: email.value,
      password: password.value
    })
    .then(async (res) => {
      if (res.status === 200) {
        router.push({ name: 'dashboard' })
      }
    })
    // error processing for login api
    .catch((err) => {
      const msg = err.response?.data?.message || err.message
      toast.add({
        severity: 'error',
        summary: 'Error',
        detail: msg,
        life: 5000
      })
    })
}
</script>

<template>
  <div
    class="surface-ground flex align-items-center justify-content-center min-h-screen min-w-screen overflow-hidden"
  >
    <div class="layout-topbar bg-transparent shadow-none">
      <router-link to="/" class="layout-topbar-logo text-dark">
        <img :src="logoUrl" alt="logo" />
        <span class="text-lg ml-2">{{ appName }}</span>
      </router-link>
    </div>
    <div class="flex flex-column align-items-center justify-content-center">
      <div
        style="
          border-radius: 56px;
          padding: 0.3rem;
          background: linear-gradient(
            180deg,
            var(--primary-color) 10%,
            rgba(33, 150, 243, 0) 30%
          );
        "
      >
        <div
          class="w-full surface-card py-8 px-5 sm:px-8"
          style="border-radius: 53px"
        >
          <div class="text-center mb-5">
            <div class="text-900 text-3xl font-medium mb-3">Login</div>
          </div>

          <div>
            <label for="email" class="block text-900 text-xl font-medium mb-2"
              >User ID</label
            >
            <InputText
              id="email"
              type="text"
              placeholder="User ID"
              class="w-full md:w-30rem mb-5"
              style="padding: 1rem"
              v-model="email"
              v-on:keyup.enter="login"
            />

            <label
              for="password"
              class="block text-900 font-medium text-xl mb-2"
              >Password</label
            >
            <Password
              id="password"
              v-model="password"
              placeholder="Password"
              :toggleMask="true"
              class="w-full mb-3"
              inputClass="w-full"
              :inputStyle="{ padding: '1rem' }"
              :feedback="false"
              v-on:keyup.enter="login"
            >
            </Password>

            <div class="flex align-items-center justify-content-center">
              <Button
                label="Sign In"
                class="w-full mt-5 p-3 text-xl"
                @click="login"
              ></Button>
            </div>
          </div>
        </div>
      </div>
    </div>
    <Toast />
  </div>
</template>

<style scoped>
.pi-eye {
  transform: scale(1.6);
  margin-right: 1rem;
}

.pi-eye-slash {
  transform: scale(1.6);
  margin-right: 1rem;
}
</style>
