# Global `!important` background suppressed per-row tint classes

## Symptom
Row-level background classes silently didn't render — no error, the rows just
stayed white: `JobHistory.vue`'s `.jh-row--workflow` (inset tint) /
`.jh-row--selected` (yellow tint) and `SegmentModelsPanel.vue`'s
`.seg-row--open` highlight.

## Cause
`_brand.scss` declared the app-wide DataTable skin with
`.p-datatable .p-datatable-tbody > tr { background: transparent !important }`
(and the same on `td`). `!important` beats any non-important rule regardless of
specificity, so the more-specific per-row tints
(`.ey-table.p-datatable … tr.jh-row--workflow { background: … }`) could never
win. The `!important`s existed only to out-cascade the base
`ey-light/theme.css`.

## Fix (pattern)
`!important` is unnecessary against the base theme: the app bundle's CSS loads
**after** the static `<link id="theme-css">` in `index.html`, so equal
specificity wins by cascade order. The only theme rules with *higher*
specificity are the size variants (`.p-datatable.p-datatable-sm …`) — cover
them by doubling each selector:

```scss
.p-datatable .p-datatable-tbody > tr > td,
.p-datatable.p-datatable-sm .p-datatable-tbody > tr > td { … }
```

Backgrounds in the global skin stay non-important so scoped/namespaced row
classes (3+ class specificity) win naturally.

## Rule of thumb
Never use `!important` in `_brand.scss` for anything a feature might want to
override per-element (backgrounds, colors on rows/cells). Reserve it for
terminal styling the design system forbids overriding (e.g. `.p-tag` shape).
When overriding the base theme, match its selector specificity instead.
