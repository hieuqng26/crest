<template>
  <div class="home-body layout-wrapper">
    <div>
      <div class="home-layout-topbar bg-transparent shadow-none">
        <router-link to="/" class="home-layout-topbar-logo text-white">
          <img :src="logoUrl" alt="logo" />
          <span class="text-lg ml-2">{{ appName }}</span>
        </router-link>

        <div class="home-layout-topbar-menu">
          <router-link to="/auth/login" class="home-layout-topbar-button">
            <i class="pi pi-sign-in text-dark"><span>Sign in</span></i>
          </router-link>
        </div>
      </div>
    </div>
    <div class="layout-main-container pb-2">
      <div class="layout-main flex align-items-center"></div>
      <div class="layout-footer border-none">
        <span class="text-xs md:text-sm lg:text-base">© {{ footerYear }} by</span>
        <span class="text-sm md:text-base lg:text-lg font-bold ml-2 text-black-400">{{
          footer
        }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
const logoUrl = import.meta.env.VITE_LOGO_URL
const appName = import.meta.env.VITE_APP_NAME
const footer = import.meta.env.VITE_FOOTER
const footerYear = import.meta.env.VITE_YEAR
</script>

<style scoped>
.home-body {
  background-image: url('@/assets/background.png');
  background-repeat: no-repeat;
  background-size: cover;
  background-position: left center;
  width: 100vw; /* Full width */
  height: 100vh; /* Full height */
}
</style>
