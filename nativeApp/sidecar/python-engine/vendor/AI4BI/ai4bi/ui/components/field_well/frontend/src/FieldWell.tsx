import { useEffect, useMemo, useState } from "react";
import { Streamlit, ComponentProps } from "streamlit-component-lib";

// Contrast-checked text for a filled accent (mirror of theme.on_accent):
// prefer white on the accent; fall back to dark ink only when white would drop
// below WCAG-AA for large/UI text (3:1) — e.g. a very bright accent.
function onAccent(hex: string): string {
  const h = (hex || "").replace("#", "");
  if (h.length < 6) return "#FFFFFF";
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const r = lin(parseInt(h.slice(0, 2), 16));
  const g = lin(parseInt(h.slice(2, 4), 16));
  const b = lin(parseInt(h.slice(4, 6), 16));
  const L = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const whiteContrast = 1.05 / (L + 0.05);
  return whiteContrast >= 3.0 ? "#FFFFFF" : "#16202B";
}

// ---- types ---------------------------------------------------------------
type Field = { name: string; label: string; kind: "measure" | "dimension" };
type Wells = { values: string[]; axis: string[]; legend: string[] };

const WELL_META: { id: keyof Wells; title: string; hint: string; accept: Field["kind"][] }[] = [
  { id: "values", title: "值 (Values)", hint: "拖入要計算的數字（指標）", accept: ["measure"] },
  { id: "axis", title: "軸 / 分組 (Axis)", hint: "拖入要分組的維度", accept: ["dimension"] },
  { id: "legend", title: "圖例 (Legend)", hint: "（選填）再切一個維度", accept: ["dimension"] },
];

const CHART_TYPES: { id: string; label: string }[] = [
  { id: "bar_chart", label: "長條圖" },
  { id: "line_chart", label: "折線圖" },
  { id: "pie_chart", label: "圓餅圖" },
  { id: "scatter", label: "散佈圖" },
  { id: "table", label: "表格" },
  { id: "pivot", label: "樞紐分析" },
];

function FieldWell({ args, theme }: ComponentProps) {
  const available: Field[] = args["available"] || [];
  const initWells: Wells = {
    values: args["wells"]?.values || [],
    axis: args["wells"]?.axis || [],
    legend: args["wells"]?.legend || [],
  };
  const initType: string = args["chart_type"] || "bar_chart";

  const [wells, setWells] = useState<Wells>(initWells);
  const [chartType, setChartType] = useState<string>(initType);
  const [dragOver, setDragOver] = useState<string | null>(null);

  // Re-sync when Python sends new args (e.g. after it applied a change).
  const argSig = JSON.stringify([initWells, initType]);
  useEffect(() => {
    setWells(initWells);
    setChartType(initType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [argSig]);

  useEffect(() => {
    Streamlit.setFrameHeight();
  });

  const fieldByName = useMemo(() => {
    const m: Record<string, Field> = {};
    available.forEach((f) => (m[f.name] = f));
    return m;
  }, [available]);

  const usedNames = new Set([...wells.values, ...wells.axis, ...wells.legend]);
  const palette = available.filter((f) => !usedNames.has(f.name));

  const t = {
    text: theme?.textColor || "#262730",
    bg: theme?.backgroundColor || "#ffffff",
    sec: theme?.secondaryBackgroundColor || "#f0f2f6",
    primary: theme?.primaryColor || "#ff4b4b",
    border: "rgba(128,128,128,0.35)",
  };

  function commit(next: Wells, type: string) {
    Streamlit.setComponentValue({
      values: next.values,
      axis: next.axis,
      legend: next.legend,
      chart_type: type,
      nonce: Date.now(),
    });
  }

  function onDropTo(target: keyof Wells | "palette", e: React.DragEvent) {
    e.preventDefault();
    setDragOver(null);
    const name = e.dataTransfer.getData("text/field");
    const from = e.dataTransfer.getData("text/from") as keyof Wells | "palette";
    if (!name) return;
    const field = fieldByName[name];
    if (!field) return;
    // type guard: a well only accepts compatible field kinds
    if (target !== "palette") {
      const meta = WELL_META.find((w) => w.id === target)!;
      if (!meta.accept.includes(field.kind)) return;
    }
    const next: Wells = {
      values: wells.values.filter((n) => n !== name),
      axis: wells.axis.filter((n) => n !== name),
      legend: wells.legend.filter((n) => n !== name),
    };
    if (target !== "palette") {
      // values well is single-measure for now (cleanest mapping); dims allow 1 each
      next[target] = [name];
    }
    setWells(next);
    if (from !== target) commit(next, chartType);
  }

  function removeFrom(well: keyof Wells, name: string) {
    const next = { ...wells, [well]: wells[well].filter((n) => n !== name) };
    setWells(next);
    commit(next, chartType);
  }

  function chip(field: Field, from: keyof Wells | "palette") {
    const icon = field.kind === "measure" ? "Σ" : "▦";
    return (
      <div
        key={field.name + from}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData("text/field", field.name);
          e.dataTransfer.setData("text/from", from);
        }}
        style={{
          display: "flex", alignItems: "center", gap: 6, cursor: "grab",
          background: from === "palette" ? t.sec : t.primary + "22",
          border: `1px solid ${from === "palette" ? t.border : t.primary}`,
          color: t.text, borderRadius: 6, padding: "4px 8px", margin: "3px 0",
          fontSize: 13,
        }}
        title={field.name}
      >
        <span style={{ opacity: 0.7 }}>{icon}</span>
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {field.label}
        </span>
        {from !== "palette" && (
          <span
            onClick={() => removeFrom(from, field.name)}
            style={{ cursor: "pointer", opacity: 0.6, fontWeight: 700 }}
            title="移除"
          >
            ×
          </span>
        )}
      </div>
    );
  }

  const wellBox = (meta: typeof WELL_META[number]) => {
    const names = wells[meta.id];
    const isOver = dragOver === meta.id;
    return (
      <div key={meta.id} style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: t.text, marginBottom: 3 }}>
          {meta.title}
        </div>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(meta.id); }}
          onDragLeave={() => setDragOver(null)}
          onDrop={(e) => onDropTo(meta.id, e)}
          style={{
            minHeight: 38, border: `1.5px dashed ${isOver ? t.primary : t.border}`,
            borderRadius: 8, padding: 5,
            background: isOver ? t.primary + "11" : t.bg,
          }}
        >
          {names.length === 0 ? (
            <div style={{ color: "#999", fontSize: 12, padding: "6px 4px" }}>{meta.hint}</div>
          ) : (
            names.map((n) => fieldByName[n] && chip(fieldByName[n], meta.id))
          )}
        </div>
      </div>
    );
  };

  // live textual preview of the resulting visual
  const valLabel = wells.values.map((n) => fieldByName[n]?.label || n).join(", ") || "—";
  const axisLabel = wells.axis.map((n) => fieldByName[n]?.label || n).join(", ") || "—";
  const typeLabel = CHART_TYPES.find((c) => c.id === chartType)?.label || chartType;

  return (
    <div style={{ fontFamily: "system-ui, 'Microsoft JhengHei', sans-serif", color: t.text }}>
      <div style={{ display: "flex", gap: 12 }}>
        {/* available fields */}
        <div
          style={{ flex: "0 0 42%" }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => onDropTo("palette", e)}
        >
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 3 }}>可用欄位</div>
          <div style={{
            border: `1px solid ${t.border}`, borderRadius: 8, padding: 5,
            minHeight: 120, maxHeight: 240, overflowY: "auto", background: t.bg,
          }}>
            {palette.length === 0
              ? <div style={{ color: "#999", fontSize: 12, padding: 6 }}>全部已使用</div>
              : palette.map((f) => chip(f, "palette"))}
          </div>
        </div>
        {/* wells */}
        <div style={{ flex: 1 }}>{WELL_META.map(wellBox)}</div>
      </div>

      {/* chart type */}
      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 3 }}>圖表類型</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {CHART_TYPES.map((c) => {
            const sel = c.id === chartType;
            const dis = c.id === "pivot" && wells.axis.length + wells.legend.length < 2;
            return (
              <button
                key={c.id}
                disabled={dis}
                onClick={() => { setChartType(c.id); commit(wells, c.id); }}
                style={{
                  fontSize: 12, padding: "4px 10px", borderRadius: 6, cursor: dis ? "not-allowed" : "pointer",
                  border: `1px solid ${sel ? t.primary : t.border}`,
                  background: sel ? t.primary : t.bg, color: sel ? onAccent(t.primary) : t.text,
                  opacity: dis ? 0.4 : 1,
                }}
                title={dis ? "樞紐需要兩個維度" : ""}
              >
                {c.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* live preview */}
      <div style={{
        marginTop: 10, fontSize: 12, color: t.text, background: t.sec,
        borderRadius: 8, padding: "7px 9px",
      }}>
        👁 預覽：以 <b>{typeLabel}</b> 顯示 <b>{valLabel}</b>
        {axisLabel !== "—" ? <> 依 <b>{axisLabel}</b></> : null}
        {wells.legend.length > 0 ? <>，再分 <b>{wells.legend.map((n) => fieldByName[n]?.label || n).join(", ")}</b></> : null}
        。
      </div>
    </div>
  );
}

export default FieldWell;
