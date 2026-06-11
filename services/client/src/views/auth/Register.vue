<script setup>
// import { ref } from 'vue'
// import router from '@/router'
// import { useToast } from 'primevue/usetoast'
// import { useStore } from 'vuex'

// const logoUrl = import.meta.env.VITE_LOGO_URL
// const appName = import.meta.env.VITE_APP_NAME
// const store = useStore()
// const toast = useToast()

// const email = ref('')
// const password = ref('')

// const register = () => {
//   store
//     .dispatch('register', { email: email.value, password: password.value, role: 'readonly' })
//     .then((res) => {
//       if (res.status === 201) {
//         router.push({ name: 'login' })
//       }
//     })
//     .catch((err) => {
//       if (err.request.status === 409) {
//         toast.add({
//           severity: 'error',
//           summary: 'Error',
//           detail: 'User already exists!',
//           life: 3000
//         })
//       }
//     })
// }
</script>

<template>
  <!-- <div
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
          background: linear-gradient(180deg, var(--primary-color) 10%, rgba(33, 150, 243, 0) 30%);
        "
      >
        <div class="w-full surface-card py-8 px-5 sm:px-8" style="border-radius: 53px">
          <div class="text-center mb-5">
            <div class="text-900 text-3xl font-medium mb-3">Register</div>
          </div>

          <div>
            <label for="email" class="block text-900 text-xl font-medium mb-2">Email</label>
            <InputText
              id="email"
              type="text"
              placeholder="Email address"
              class="w-full md:w-30rem mb-5"
              style="padding: 1rem"
              v-model="email"
            />

            <label for="password" class="block text-900 font-medium text-xl mb-2">Password</label>
            <Password
              id="password"
              v-model="password"
              placeholder="Password"
              :toggleMask="true"
              class="w-full mb-3"
              inputClass="w-full"
              :inputStyle="{ padding: '1rem' }"
            >
              <template #footer>
                <Divider />
                <ul class="pl-2 ml-2 mt-0" style="line-height: 1.5">
                  <li>Minimum 8 characters</li>
                  <li>At least 1 lowercase, 1 uppercase, 1 numeric</li>
                  <li>At least 1 special character (!@#$%^&*)</li>
                </ul>
              </template>
            </Password>

            <Button label="Sign Up" class="w-full mt-5 p-3 text-xl" @click="register"></Button>
            <p class="mt-3">
              Already have account?
              <router-link
                to="/auth/login"
                class="font-bold no-underline text-right cursor-pointer"
                style="color: var(--primary-color)"
                >Sign In</router-link
              >
            </p>
          </div>
        </div>
      </div>
    </div>
    <Toast />
  </div> -->
</template>

<style scoped>
/* .pi-eye {
  transform: scale(1.6);
  margin-right: 1rem;
}

.pi-eye-slash {
  transform: scale(1.6);
  margin-right: 1rem;
} */
</style>
