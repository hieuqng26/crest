<script setup>
defineProps({
  /** Array of column definitions: { label: string, align?: 'left'|'right', width?: string } */
  columns: { type: Array, required: true },
  /** Horizontal bleed in px to cancel out the parent panel's padding (default 16px) */
  bleed: { type: Number, default: 16 },
})
</script>

<template>
  <div class="ey-table-scroll" :style="{ margin: `0 -${bleed}px`, padding: `0 ${bleed}px` }">
    <table class="ey-table">
      <thead>
        <tr>
          <th
            v-for="col in columns"
            :key="col.label"
            :class="col.align === 'right' ? 'ta-right' : ''"
            :style="col.width ? { width: col.width } : {}"
          >{{ col.label }}</th>
        </tr>
      </thead>
      <tbody>
        <slot />
      </tbody>
    </table>
  </div>
</template>

<!--
  Not scoped — styles must reach <tr>/<td> rendered by the parent's slot content.
  All rules are namespaced under .ey-table to avoid collisions.
-->
<style>
.ey-table-scroll { overflow-x: auto; }

.ey-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

/* Header divider — always full table width */
.ey-table thead tr {
  border-bottom: 2px solid var(--ink);
}
.ey-table th {
  padding: 6px 12px 9px 0;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.07em;
  color: var(--text-color-muted);
  text-align: left;
  white-space: nowrap;
}
.ey-table th:first-child { padding-left: 0; }
.ey-table th.ta-right { text-align: right; }

/* Row defaults */
.ey-table tbody tr { border-bottom: 1px solid var(--surface-border-row); }
.ey-table tbody tr:last-child { border-bottom: none; }
.ey-table tbody tr:hover { background: var(--surface-hover); }

/* Cell defaults */
.ey-table td {
  padding: 10px 12px 10px 0;
  font-size: 12.5px;
  vertical-align: middle;
}
.ey-table td:first-child { padding-left: 0; }
.ey-table td.ta-right { text-align: right; }

/* Opt-out of row hover (e.g. customize expand rows) */
.ey-table tbody tr.no-hover:hover { background: transparent; }
</style>
