/* eslint-env node */
require('@rushstack/eslint-patch/modern-module-resolution')

// create-vue standard config for eslint 8 (.eslintrc era — the lint script
// uses --ext/--ignore-path, which the flat config doesn't support). Formatting
// is delegated to Prettier via skip-formatting so ESLint and `npm run format`
// never disagree; ESLint here only flags real problems (unused vars, undefined
// refs, Vue template mistakes).
module.exports = {
  root: true,
  extends: [
    'plugin:vue/vue3-essential',
    'eslint:recommended',
    '@vue/eslint-config-prettier/skip-formatting',
  ],
  parserOptions: {
    ecmaVersion: 'latest',
  },
  rules: {
    // Routed page views are legitimately single-word (Login, Dashboard,
    // Error, Datasets…); renaming them for the linter isn't worth it.
    'vue/multi-word-component-names': 'off',
  },
  overrides: [
    {
      // AppConfig is a side-effect-only component (applies the font-scale on
      // mount) and renders nothing by design — an empty template root is
      // intentional, not a mistake.
      files: ['src/layout/AppConfig.vue'],
      rules: { 'vue/valid-template-root': 'off' },
    },
  ],
}
