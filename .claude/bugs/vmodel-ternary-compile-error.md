# Bug: v-model ternary breaks the page (compile error)

**Symptom:** A jobs page (e.g. Forecast All Jobs) fails to load / blank screen after
adding row selection.

**Cause:** A PrimeVue `v-model` was bound to an inline ternary:
`v-model:selection="selectMode ? selection : undefined"`. `v-model` requires a valid
assignable member expression; a ternary is not, so the template fails to compile.

**Fix:** Always bind `v-model` to a plain ref and control behavior with the relevant
prop instead:
```vue
<DataTable v-model:selection="selection" :selectionMode="selectMode ? 'multiple' : null">
```

**Prevention:** `v-model:X` must be a ref/reactive property, never a ternary,
function call, or other non-assignable expression.
