# Field Well — drag-and-drop custom Streamlit component

A Power BI-style Visualizations pane: drag fields between **可用欄位 / 值 / 軸 / 圖例**
wells with live preview. Bidirectional React/TS component built with the
Streamlit Components API.

## Layout
- `frontend/src/FieldWell.tsx` — the React component (HTML5 drag-drop + preview).
- `frontend/dist/` — built output, **committed** so the app renders without a
  Node build. Served by `declare_component(path=...)`.
- `__init__.py` — Python wrapper (`field_well(...)`, `is_available()`).

## Rebuilding the frontend
Only needed if you change `frontend/src`:

```bash
cd ai4bi/ui/components/field_well/frontend
npm install      # first time only (node_modules is gitignored)
npm run build    # regenerates dist/  → commit the new dist/
```

If `dist/` is missing, `is_available()` returns False and the app falls back to
the dropdown field-well in the Visualizations pane (no crash).

## Contract
- Python → component: `available=[{name,label,kind}]`, `wells={values,axis,legend}`,
  `chart_type`.
- component → Python: `{values, axis, legend, chart_type, nonce}` on user change.
  `nonce` lets the caller apply each user action exactly once.
- The result is mapped to a governed `query/metrics` + `query/dimensions` +
  `visualization/visual_type` patch in `app._apply_field_well_result`.
