# Semiconductor Process Demo Data Product

This package is a tabular JSON demo dataset for validating AI-for-BI with
semiconductor manufacturing use cases. It is designed for reusable dashboard
components rather than a dedicated semiconductor GUI.

## Package Layout

| Path | Grain | Purpose |
| --- | --- | --- |
| `blocks/calendar_dim.json` | one row per date | Time filtering and trend grouping |
| `blocks/lot_dim.json` | one row per manufacturing lot | Product, route and lot priority slicing |
| `blocks/wafer_dim.json` | one row per wafer | Wafer-to-lot traceability |
| `blocks/tool_dim.json` | one row per equipment tool | Tool group and chamber analysis |
| `blocks/process_step_dim.json` | one row per route step | Process-stage analysis |
| `blocks/foup_dim.json` | one row per FOUP carrier | Carrier usage analysis |
| `blocks/process_move_fact.json` | one row per wafer process move | Queue time, processing time and move throughput |
| `blocks/wafer_yield_fact.json` | one row per wafer final yield result | Yield and defect trend analysis |
| `semantic_model.json` | model metadata | Certified relationship and safe-composition rules |
| `baselines.json` | expected results | Stable query assertions for tests and demos |

All block JSON files conform to the current `ai4bi.blocks.contracts.DataBlockContract`
schema and use inline records for local demonstration.

## Why This Model

The model separates physical entities from events:

- A `lot` groups wafers and describes planned production context.
- A `wafer` belongs to one lot in this demo.
- A `process_move` records one wafer completing one process step on one tool
  while using a FOUP at that event time.
- A `wafer_yield` record captures final inspected die counts after processing.
- A `tool`, `process_step`, `FOUP` and `calendar date` are reusable dimensions.

This arrangement supports ordinary self-service BI questions:

| Question | Primary Fact | Safe Dimensions | Suitable Visual |
| --- | --- | --- | --- |
| How is average queue time trending by day? | `process_move_fact` | date, step, tool group, product family | line chart |
| Which etch tool has higher queue time or throughput? | `process_move_fact` | tool, step | bar chart / table |
| Is final wafer yield trending down by tool or product? | `wafer_yield_fact` | date, tool, lot/product | line chart |
| Which lots contain failing wafers? | `wafer_yield_fact` | lot, wafer | table |
| Which FOUP carried wafers through delayed moves? | `process_move_fact` | FOUP, step | table / bar chart |

## Safe Join Rules

The intended star-schema joins are fact-to-dimension many-to-one relationships:

```text
process_move_fact -> calendar_dim / wafer_dim / lot_dim / tool_dim /
                     process_step_dim / foup_dim

wafer_yield_fact -> calendar_dim / wafer_dim / lot_dim / tool_dim /
                    process_step_dim
```

The two fact blocks must not be joined row-by-row for a dashboard metric.
For example, yield versus queue time must first aggregate each fact to a
certified shared grain such as `lot_id + step_id`, then combine the aggregated
results. Otherwise each measurement can multiply multiple move records.

## Important Manufacturing Boundaries

- `foup_id` is recorded on `process_move_fact`; FOUP occupancy is temporal and
  is not a permanent property of a lot or wafer.
- A tool recorded on `wafer_yield_fact` means the source process tool
  whose processed wafer is being evaluated, not necessarily the metrology tool.
- WIP snapshots, rework loops, split/merge lots and wafer genealogy are not
  represented in this first package. They require additional contracts because
  their aggregation and traceability rules differ from simple event facts.
- The current executor compiles only direct certified fact-to-dimension
  `many_to_one` joins. Both fact blocks still carry selected display
  dimensions such as `product_family` for simple filtering; detail
  fact-to-fact composition remains deliberately unavailable.
- Yield is non-additive. Authoritative roll-up must be calculated as
  `SUM(good_die) / SUM(tested_die) * 100`; `yield_pct` is included only for
  wafer-row display and must not be summed or averaged for production use.
- Metrics in this package are illustrative, not production process-control
  limits or certified fab KPI definitions.

## Example Dashboard

The current Streamlit report canvas is an editable **validated demo draft**.
It uses these blocks and a certified direct relationship path, but it is not a
published or authorization-controlled dashboard:

| Component | Metric | Dimension / Filter |
| --- | --- | --- |
| KPI | total `move_count` | selected date / step |
| KPI | average `queue_time_hr` | selected date / step |
| Trend | average `queue_time_hr` | `event_date`, filter `step_id = ETCH` |
| Bar | average `queue_time_hr` | joined `tool_dim.tool_id`, filter `step_id = ETCH` |
| Table | total moves and average queue time | joined `tool_dim.tool_id` / `vendor` |

## Draft Authoring Workflow

The MVP report workspace now supports:

- Manual slicers and Tool ID / Vendor comparison updates as report history entries.
- A selected-visual assistant that creates a pending proposal before applying
  approved changes such as `把趨勢線改成紅色` or `只看 Logic-B`.
- Cross-filter broadcast from the trend and tool bar visuals into compatible
  same-page visuals.
- `Apply Proposal`, `Cancel Proposal`, `Undo` and `Redo`.
- Add/reorder/delete-page proposal workflows for report canvas maintenance.
- `Save Local Draft` and `Load Draft`, persisting executable query and style
  state as local JSON under `draft_reports/` when a user chooses to save.
- Publish/share snapshot storage plus a sidebar browser for loading published
  read-only snapshots.

Formal team lifecycle governance remains intentionally limited. Production
authorization enforcement, role policy, audit-purpose metadata and enterprise
sharing workflows are still deferred.
