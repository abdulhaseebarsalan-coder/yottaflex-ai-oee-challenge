# Empirical Distributions and Scenario Evidence (Full Dataset)

> **Dataset Profile**: Full Production Horizon (90 Days, 30 Machines, 270 Shifts, 8,100 Aggregates)  
> **Generated Timestamp**: `2026-10-28T03:10:20.583169+00:00`  
> **Source Data**: Evaluated strictly from `data/full/` transactional CSVs and `oee_aggregates.csv`.

---

## 1. Production Orders Lifecycle Status Distribution

| Order Status | Count | Percentage | Operational Semantics |
|:---|---:|---:|:---|
| `CANCELLED` | 1 | 0.14% | Rescheduled or superseded manufacturing work orders before execution. |
| `COMPLETED` | 687 | 99.57% | Standard orders scheduled and executed to completion within historical horizon. |
| `IN_PROGRESS` | 2 | 0.29% | Active production runs ongoing across boundary transitions at horizon close. |

## 2. Equipment State Mix and Operational Timeline Breakdown

| Machine State | Event Count | Count % | Total Duration (hrs) | Duration % | Primary Operational Driver |
|:---|---:|---:|---:|---:|:---|
| `RUNNING` | 62,278 | 51.65% | 53,049.3 | 81.86% | Nominal parts fabrication under active manufacturing work orders |
| `PLANNED_DOWNTIME` | 24,300 | 20.15% | 8,101.0 | 12.5% | Autonomous maintenance, preventive inspections, and scheduled meal/rest breaks |
| `UNPLANNED_DOWNTIME` | 19,468 | 16.15% | 1,330.6 | 2.05% | Corrective maintenance, electrical/mechanical jams, micro-stops, tool fractures |
| `STARVED` | 5,992 | 4.97% | 547.3 | 0.84% | Upstream feeder starvation / raw material staging delay |
| `BLOCKED` | 4,428 | 3.67% | 404.7 | 0.62% | Downstream conveyor / buffer saturation halting production |
| `CHANGEOVER` | 4,110 | 3.41% | 1,374.5 | 2.12% | Product die/fixture swap, tooling calibration, and setup verification |

## 3. Downtime Taxonomy and Loss Attribution Breakdown

| Downtime Reason Code | Event Count | Event % | Total Duration (hrs) | Duration % | Availability Treatment |
|:---|---:|---:|---:|---:|:---|
| `DT-PLANNED-BREAK` | 24,300 | 41.68% | 8,101.0 | 68.9% | Excluded from Planned Production Time (PPT) |
| `DT-UNPLANNED-MICRO` | 7,497 | 12.86% | 234.2 | 1.99% | Penalizes Operating Time & Availability directly |
| `DT-STOP-STARVED` | 5,992 | 10.28% | 547.3 | 4.65% | Penalizes Operating Time & Availability directly |
| `DT-STOP-BLOCKED` | 4,428 | 7.6% | 404.7 | 3.44% | Penalizes Operating Time & Availability directly |
| `DT-CHANGEOVER-SETUP` | 4,110 | 7.05% | 1,374.5 | 11.69% | Penalizes Operating Time & Availability directly |
| `DT-UNPLANNED-TOOL` | 4,029 | 6.91% | 368.2 | 3.13% | Penalizes Operating Time & Availability directly |
| `DT-UNPLANNED-JAM` | 3,987 | 6.84% | 368.9 | 3.14% | Penalizes Operating Time & Availability directly |
| `DT-UNPLANNED-ELEC` | 3,955 | 6.78% | 359.4 | 3.06% | Penalizes Operating Time & Availability directly |

## 4. Required Scenario Audits and Evidence

### A. Micro-Stop Events (`DT-UNPLANNED-MICRO`)
- **Generating Rule & Definition**: Generated via `stop_dur = randint(45, min(stop_rem, 180))` (nominal range 45s to 180s) representing momentary equipment stalls, minor feeder misfeeds, optical sensor trips, or brief part dislodgements.
- **OEE Governance Treatment**: Explicitly typed as `UNPLANNED_DOWNTIME` with reason code `DT-UNPLANNED-MICRO`. Unlike planned breaks, micro-stops are not excluded from Planned Production Time (PPT); they decrement Operating Time and penalize Availability.
- **Total Micro-Stop Events**: **7,497** records (234.2 hours).
- **Duration Statistics**: Mean=112.441s, Min=45s, Median=112s, Max=1055s, Std=41.9991s (in the clean baseline, 100% of micro-stops fall within [45s, 180s]; the 2 records exceeding 180s are EVT-MCH-LINE-02-04-001571 [1016s] and EVT-MCH-LINE-02-04-002463 [1055s] due to EC-01 overlapping state start-time inflation by +900s).
- **Sample Micro-Stop Evidence Records**:
```json
[
  {
    "event_id": "EVT-MCH-LINE-01-01-000008",
    "machine_id": "MCH-LINE-01-01",
    "shift_id": "SHIFT-2026-01-01-A",
    "order_id": "PO-2026-000001",
    "state": "UNPLANNED_DOWNTIME",
    "start_time": "2026-01-01T09:44:42Z",
    "end_time": "2026-01-01T09:46:15Z",
    "duration_sec": "93",
    "reason_code": "DT-UNPLANNED-MICRO"
  },
  {
    "event_id": "EVT-MCH-LINE-01-01-000016",
    "machine_id": "MCH-LINE-01-01",
    "shift_id": "SHIFT-2026-01-01-A",
    "order_id": "PO-2026-000001",
    "state": "UNPLANNED_DOWNTIME",
    "start_time": "2026-01-01T12:54:02Z",
    "end_time": "2026-01-01T12:55:28Z",
    "duration_sec": "86",
    "reason_code": "DT-UNPLANNED-MICRO"
  },
  {
    "event_id": "EVT-MCH-LINE-01-01-000060",
    "machine_id": "MCH-LINE-01-01",
    "shift_id": "SHIFT-2026-01-02-C",
    "order_id": "PO-2026-000004",
    "state": "UNPLANNED_DOWNTIME",
    "start_time": "2026-01-02T23:25:57Z",
    "end_time": "2026-01-02T23:27:47Z",
    "duration_sec": "110",
    "reason_code": "DT-UNPLANNED-MICRO"
  }
]
```

### B. Changeovers (`DT-CHANGEOVER-SETUP`)
- **Total Setup Events**: **4,110** records across line toolings.
- **Duration Statistics**: Mean=1203.9854s (20.1m), Min=900s, Max=1500s.
- **Sample Changeover Evidence Records**:
```json
[
  {
    "event_id": "EVT-MCH-LINE-01-01-000036",
    "machine_id": "MCH-LINE-01-01",
    "shift_id": "SHIFT-2026-01-02-A",
    "order_id": "PO-2026-000002",
    "state": "CHANGEOVER",
    "start_time": "2026-01-02T06:00:00Z",
    "end_time": "2026-01-02T06:19:00Z",
    "duration_sec": "1140",
    "reason_code": "DT-CHANGEOVER-SETUP"
  },
  {
    "event_id": "EVT-MCH-LINE-01-01-000044",
    "machine_id": "MCH-LINE-01-01",
    "shift_id": "SHIFT-2026-01-02-B",
    "order_id": "PO-2026-000003",
    "state": "CHANGEOVER",
    "start_time": "2026-01-02T14:00:00Z",
    "end_time": "2026-01-02T14:16:00Z",
    "duration_sec": "960",
    "reason_code": "DT-CHANGEOVER-SETUP"
  },
  {
    "event_id": "EVT-MCH-LINE-01-01-000056",
    "machine_id": "MCH-LINE-01-01",
    "shift_id": "SHIFT-2026-01-02-C",
    "order_id": "PO-2026-000004",
    "state": "CHANGEOVER",
    "start_time": "2026-01-02T22:00:00Z",
    "end_time": "2026-01-02T22:22:00Z",
    "duration_sec": "1320",
    "reason_code": "DT-CHANGEOVER-SETUP"
  }
]
```

### C. Planned Breaks per Shift (`DT-PLANNED-BREAK`)
- **Total Shift Calendar Records**: **270** shifts (90 days × 3 shifts).
- **Total Scheduled Rest Breaks**: **24,300** break events across 8,100 machine-shifts.
- **Breaks per Machine-Shift**: **3 scheduled breaks per machine-shift** (90 scheduled breaks per calendar shift across all 30 machines: Break 1 [15m], Lunch [30m], Break 2 [15m]).
- **Mean Break Duration**: **1200.1s** (20.0 min average duration, summing to exactly 60.0 min scheduled deduction from PPT per shift).

### D. Count Corrections (`correction_ref_id` Audit)
- **Total Production Pulse Records**: **588,938** pulse records.
- **Negative Sensor Reconciliation Records**: **2,932** records.
- **Audit Linkage Rate**: **2,922** records (99.66%) strictly populate `correction_ref_id` referencing the corrupted pulse ID (the remaining 10 records represent the injected unreferenced count drop anomalies [EC-02] flagged by `VAL-COUNT-001`).
- **Sample Reconciled Pulse Pair**:
```json
{
  "correction_record": {
    "count_id": "CNT-PO-2026-000001-000077",
    "order_id": "PO-2026-000001",
    "machine_id": "MCH-LINE-01-06",
    "shift_id": "SHIFT-2026-01-01-A",
    "timestamp": "2026-01-01T07:17:35Z",
    "count_delta": "-7",
    "cumulative_count": "197",
    "is_correction": "True",
    "correction_ref_id": "CNT-PO-2026-000001-000076"
  },
  "original_record": {
    "count_id": "CNT-PO-2026-000001-000076",
    "order_id": "PO-2026-000001",
    "machine_id": "MCH-LINE-01-06",
    "shift_id": "SHIFT-2026-01-01-A",
    "timestamp": "2026-01-01T07:17:30Z",
    "count_delta": "14",
    "cumulative_count": "204",
    "is_correction": "False",
    "correction_ref_id": ""
  }
}
```

## 5. Deterministic Scrap/Rework Rule & Product Defect Distribution

### Deterministic Scrap/Rework Formulation
Scrap and rework quantities are produced using the strict deterministic physical loss model:
$$\text{defect\_rate} = \text{clamp}\left(p_{\text{base}}(\text{product}) \times f_{\text{crit}}(\text{machine}) \times m_{\text{transient}},\ 0.005,\ 0.25\right)$$
Where:
- $p_{\text{base}}(\text{product}) \in [0.015, 0.045]$: Product base defect rate derived deterministically from product index.
- $f_{\text{crit}}(\text{machine}) \in \{1.2\text{ (High)}, 1.0\text{ (Medium)}, 0.8\text{ (Low)}\}$: Machine criticality structural factor.
- $m_{\text{transient}}$: Non-linear transient factor:
  - **$2.5\times$** within 60 minutes after a changeover tooling swap (`DT-CHANGEOVER-SETUP`).
  - **$2.0\times$** within 60 minutes following an unplanned breakdown restart (`UNPLANNED_DOWNTIME`).
  - **$1.0\times$** during steady-state autonomous production.

### Observed Post-Changeover Multiplier Effect
- **Transient Post-Changeover Scrap Rate**: **3.783%** (4,893 scrap / 129,330 inspected).
- **Steady-State Scrap Rate**: **2.092%** (7,460 scrap / 356,670 inspected).
- **Empirical Multiplier**: **1.81x** elevated defect generation during thermal and mechanical stabilization windows.

### Scrap and Rework Rates by Product

| Product ID | Inspected Units | Passed Units | Scrap Units | Rework Units | Scrap Rate % | Rework Rate % | Conforming Quality Yield % |
|:---|---:|---:|---:|---:|---:|---:|---:|
| `PRD-0001` | 29,360 | 28,086 | 824 | 450 | 2.807% | 1.533% | 97.193% |
| `PRD-0002` | 20,640 | 19,919 | 497 | 269 | 2.408% | 1.303% | 97.592% |
| `PRD-0003` | 26,300 | 25,599 | 506 | 260 | 1.924% | 0.989% | 98.076% |
| `PRD-0004` | 11,320 | 10,794 | 419 | 171 | 3.701% | 1.511% | 96.299% |
| `PRD-0005` | 25,640 | 24,662 | 627 | 351 | 2.445% | 1.369% | 97.555% |
| `PRD-0006` | 25,080 | 24,358 | 459 | 263 | 1.83% | 1.049% | 98.17% |
| `PRD-0007` | 26,480 | 25,134 | 911 | 435 | 3.44% | 1.643% | 96.56% |
| `PRD-0008` | 23,400 | 22,407 | 695 | 333 | 2.97% | 1.423% | 97.03% |
| `PRD-0009` | 23,320 | 22,543 | 494 | 283 | 2.118% | 1.214% | 97.882% |
| `PRD-0010` | 23,660 | 23,078 | 419 | 197 | 1.771% | 0.833% | 98.229% |
| `PRD-0011` | 25,440 | 24,325 | 816 | 397 | 3.208% | 1.561% | 96.792% |
| `PRD-0012` | 28,740 | 27,733 | 653 | 354 | 2.272% | 1.232% | 97.728% |
| `PRD-0013` | 26,300 | 25,623 | 433 | 244 | 1.646% | 0.928% | 98.354% |
| `PRD-0014` | 28,160 | 26,773 | 980 | 468 | 3.48% | 1.662% | 96.52% |
| `PRD-0015` | 25,180 | 24,163 | 648 | 369 | 2.573% | 1.465% | 97.427% |
| `PRD-0016` | 26,500 | 25,663 | 532 | 305 | 2.008% | 1.151% | 97.992% |
| `PRD-0017` | 26,780 | 25,392 | 978 | 473 | 3.652% | 1.766% | 96.348% |
| `PRD-0018` | 26,120 | 25,082 | 660 | 378 | 2.527% | 1.447% | 97.473% |
| `PRD-0019` | 21,820 | 21,027 | 563 | 264 | 2.58% | 1.21% | 97.42% |
| `PRD-0020` | 15,760 | 15,368 | 239 | 153 | 1.516% | 0.971% | 98.484% |

## 6. OEE Metric Distributions and Operational Spread

### Overall Metric Spread Across All 8,100 Shift-Machine Aggregates

| Metric | Mean | Std Dev | Min | 25th % | Median | 75th % | Max |
|:---|---:|---:|---:|---:|---:|---:|---:|
| **Oee** | 0.7727 | 0.0580 | 0.0000 | 0.7440 | 0.7749 | 0.8062 | 0.8914 |
| **Availability** | 0.9356 | 0.0333 | 0.8241 | 0.9118 | 0.9358 | 0.9609 | 1.0000 |
| **Performance** | 0.8461 | 0.0442 | 0.0000 | 0.8360 | 0.8492 | 0.8614 | 0.8960 |
| **Quality** | 0.9755 | 0.0226 | 0.8401 | 0.9601 | 0.9800 | 1.0000 | 1.0000 |

### OEE Spread by Shift Code

| Shift | Mean OEE | Std Dev | Min | 25th % | Median | 75th % | Max |
|:---|---:|---:|---:|---:|---:|---:|---:|
| **Shift A** | 0.7713 | 0.0579 | 0.0000 | 0.7430 | 0.7733 | 0.8048 | 0.8864 |
| **Shift B** | 0.7730 | 0.0586 | 0.0000 | 0.7438 | 0.7747 | 0.8070 | 0.8914 |
| **Shift C** | 0.7737 | 0.0575 | 0.0000 | 0.7453 | 0.7765 | 0.8063 | 0.8894 |

### OEE Spread by Machine (Sample Stations)

| Machine ID | Mean OEE | Std Dev | Min | Median | Max |
|:---|---:|---:|---:|---:|---:|
| `MCH-LINE-01-01` | 0.7633 | 0.0935 | 0.0000 | 0.7742 | 0.8914 |
| `MCH-LINE-01-02` | 0.7605 | 0.0934 | 0.0000 | 0.7690 | 0.8843 |
| `MCH-LINE-01-03` | 0.7729 | 0.0928 | 0.0000 | 0.7793 | 0.8821 |
| `MCH-LINE-01-04` | 0.7679 | 0.0930 | 0.0000 | 0.7728 | 0.8855 |
| `MCH-LINE-01-05` | 0.7678 | 0.0936 | 0.0000 | 0.7745 | 0.8784 |
| `MCH-LINE-01-06` | 0.7670 | 0.0928 | 0.0000 | 0.7773 | 0.8827 |
| `MCH-LINE-02-01` | 0.7696 | 0.0490 | 0.6151 | 0.7700 | 0.8702 |
| `MCH-LINE-02-02` | 0.7747 | 0.0466 | 0.6356 | 0.7731 | 0.8833 |
| `MCH-LINE-02-03` | 0.7751 | 0.0486 | 0.6300 | 0.7779 | 0.8869 |
| `MCH-LINE-02-04` | 0.7771 | 0.0427 | 0.6466 | 0.7786 | 0.8753 |
