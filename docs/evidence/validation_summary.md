# Validation Summary Report (Starter Profile)

- **Profile**: `starter`
- **Seed**: `20261022`
- **Total Violations Detected**: `10`
- **Reproducibility Verdict**: `PASS (100% Bitwise Identical)`

## Findings Breakdown by Validation Rule

| Rule ID | Severity | Table | Findings Count |
| :--- | :--- | :--- | :---: |
| `VAL-COUNT-001` | `ERROR` | `production_counts.csv` | 1 |
| `VAL-PERF-001` | `ERROR` | `production_orders.csv` | 1 |
| `VAL-QUAL-001` | `ERROR` | `quality_inspections.csv` | 2 |
| `VAL-STATE-001` | `ERROR` | `state_events.csv` | 1 |
| `VAL-TIME-002` | `ERROR` | `state_events.csv` | 2 |
| `VAL-TIME-003` | `ERROR` | `state_events.csv` | 1 |
| `VAL-TIME-005` | `ERROR` | `state_events.csv` | 2 |

## Findings Breakdown by Table

| Table Name | Violations |
| :--- | :---: |
| `production_counts.csv` | 1 |
| `production_orders.csv` | 1 |
| `quality_inspections.csv` | 2 |
| `state_events.csv` | 6 |
