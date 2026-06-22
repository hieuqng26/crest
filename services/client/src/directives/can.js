import store from '@/store'

export const can = {
  mounted(el, binding) {
    if (!store.getters.can(binding.value)) {
      el.parentNode && el.parentNode.removeChild(el)
    }
  }
}
