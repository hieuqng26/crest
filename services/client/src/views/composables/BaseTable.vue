<script setup>
// Shared "EY table" shell, now backed by PrimeVue DataTable/Column instead of a
// hand-rolled <table>. Consumers pass a column config + row array and render
// cells through `#cell-<field>` slots (falling back to the raw row value).
// Optional inline row expansion is driven externally via `expandedRows`
// (v-model) + the `#expansion` slot. The visual language — flush-left cells,
// 2px ink header rule, warm row hover, 1px row dividers — is unchanged and
// driven entirely through the theme tokens.
import { computed } from 'vue'

const props = defineProps({
  /** Column defs: { field?: string, label: string, align?: 'left'|'right', width?: string, hideHeader?: boolean } */
  columns: { type: Array, required: true },
  /** Row objects. */
  value: { type: Array, default: () => [] },
  /** Unique row identifier key (required for selection/expansion). */
  dataKey: { type: String, default: null },
  /** Per-row class — string | object | (row) => string|object. */
  rowClass: { type: [Function, String, Object], default: null },
  /** Expanded rows (v-model) for the inline `#expansion` panel. When a
   *  `dataKey` is set, PrimeVue expects a keyed map ({ [key]: true }); without
   *  one it expects an array of row objects. */
  expandedRows: { type: [Array, Object], default: null },
  /** Whether rows respond to clicks (adds pointer cursor + emits row-click). */
  rowHover: { type: Boolean, default: true },
  /** Horizontal bleed in px to cancel out the parent panel's padding (default 16px). */
  bleed: { type: Number, default: 16 },
})

const emit = defineEmits(['row-click', 'update:expandedRows'])

// A stable field for every column so slot/keys resolve even when a caller
// omits `field` (e.g. an actions column).
const cols = computed(() =>
  props.columns.map((c, i) => ({ ...c, field: c.field ?? `__col_${i}` }))
)

const rowClassFn = (row) =>
  typeof props.rowClass === 'function' ? props.rowClass(row) : props.rowClass

const onRowClick = (e) => emit('row-click', e.data, e.originalEvent)
const onExpandUpdate = (val) => emit('update:expandedRows', val)
</script>

<template>
  <div class="ey-table-scroll" :style="{ margin: `0 -${bleed}px`, padding: `0 ${bleed}px` }">
    <DataTable
      :value="value"
      :dataKey="dataKey"
      :rowClass="rowClassFn"
      :expandedRows="expandedRows ?? undefined"
      class="ey-table"
      :class="{ 'ey-table--no-hover': !rowHover }"
      @row-click="onRowClick"
      @update:expandedRows="onExpandUpdate"
    >
      <template #empty>
        <slot name="empty" />
      </template>

      <Column
        v-for="col in cols"
        :key="col.field"
        :field="col.field"
        :header="col.hideHeader ? '' : col.label"
        :headerClass="col.align === 'right' ? 'ey-th-right' : null"
        :bodyClass="col.align === 'right' ? 'ey-td-right' : null"
        :style="col.width ? { width: col.width } : {}"
      >
        <template v-if="$slots[`header-${col.field}`]" #header>
          <slot :name="`header-${col.field}`" :col="col" />
        </template>
        <template #body="{ data }">
          <slot :name="`cell-${col.field}`" :row="data" :data="data">
            {{ data[col.field] ?? '' }}
          </slot>
        </template>
      </Column>

      <template v-if="$slots.expansion" #expansion="{ data }">
        <slot name="expansion" :row="data" :data="data" />
      </template>
    </DataTable>
  </div>
</template>

<!--
  Not scoped — DataTable renders its own DOM (some of it teleported for the
  scroller); rules are namespaced under .ey-table to avoid collisions. Colors
  come exclusively from theme tokens so the shell tracks the active theme.
-->
<style>
.ey-table-scroll { overflow-x: auto; }

/* Strip PrimeVue's default card chrome — the parent panel owns the border. */
.ey-table.p-datatable .p-datatable-wrapper { background: transparent; }
.ey-table.p-datatable table { border-collapse: collapse; width: 100%; font-size: 13px; }

/* Header — typography/ink rule come from the global _brand.scss skin; this
   variant only re-shapes the cell box: flush-left first cell, tighter pad. */
.ey-table.p-datatable .p-datatable-thead > tr > th {
  background: transparent;
  padding: 6px 12px 9px 0;
  text-align: left;
  white-space: nowrap;
}
.ey-table.p-datatable .p-datatable-thead > tr > th:first-child { padding-left: 0; }
.ey-table.p-datatable .p-datatable-thead > tr > th.ey-th-right { text-align: right; }
.ey-table.p-datatable .p-datatable-thead > tr > th.ey-th-right .p-column-header-content { justify-content: flex-end; }

/* Rows — 1px divider, warm hover. */
.ey-table.p-datatable .p-datatable-tbody > tr {
  background: transparent;
  border-bottom: 1px solid var(--surface-border-row);
  transition: background 0.12s;
}
.ey-table.p-datatable .p-datatable-tbody > tr:last-child { border-bottom: none; }
.ey-table:not(.ey-table--no-hover).p-datatable .p-datatable-tbody > tr:not(.p-datatable-row-expansion):hover {
  background: var(--surface-hover);
}

/* Cells — flush-left first cell, right-align opt-in. Font/color come from
   the global skin (13px); only the box changes here. */
.ey-table.p-datatable .p-datatable-tbody > tr > td {
  background: inherit;
  border-bottom: 0;
  padding: 10px 12px 10px 0;
  vertical-align: middle;
}
.ey-table.p-datatable .p-datatable-tbody > tr > td:first-child { padding-left: 0; }
.ey-table.p-datatable .p-datatable-tbody > tr > td.ey-td-right { text-align: right; }

/* Expansion row — let the slot content own its own padding/background. */
.ey-table.p-datatable .p-datatable-tbody > tr.p-datatable-row-expansion > td {
  padding: 0;
  border-bottom: 1px solid var(--surface-border-row);
}
.ey-table.p-datatable .p-datatable-tbody > tr.p-datatable-row-expansion:hover { background: transparent; }

/* Empty message cell — no flush-left inset. */
.ey-table.p-datatable .p-datatable-tbody > tr.p-datatable-emptymessage > td { padding: 0; }
</style>
