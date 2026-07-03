# Bug: PrimeVue row-filter dropdown silently returns zero rows

**Symptom:** A PrimeVue `DataTable` with `filterDisplay="row"`: selecting a value
in a per-column `MultiSelect` filter (e.g. filtering "country" = "UK") always
returns "No rows found", even though matching rows clearly exist.

**Cause:** The `filters` model object's `matchMode` was left at its initial value
(`FilterMatchMode.CONTAINS`, set when the filter row was first created) even after
the column's widget was switched to a `MultiSelect`. The `#filter` slot's
`filterCallback()` reads whatever `matchMode` is currently in the model — it
doesn't infer the mode from which widget is rendered. Server-side, the array value
(`["UK"]`) got serialized into a substring "contains" check (`str(['UK'])` never
matches anything), so every request came back empty.

**Fix:** Whenever a column is (re)classified as categorical and its filter widget
becomes a `MultiSelect`, explicitly update `filters[field].matchMode` to
`FilterMatchMode.IN` (and reset `.value` to `[]`) at the same time — don't just
swap the rendered widget. See `markCategorical()` in
`services/client/src/components/Table/CommonDataTable.vue`.

**Prevention:** Whenever a `filterDisplay="row"` column's widget type changes
dynamically (text ↔ dropdown/multiselect), always sync `matchMode` alongside the
widget choice — they're two views of the same decision, not independent state.
Verify by round-tripping the actual network request payload, not just the UI
rendering the widget correctly.
