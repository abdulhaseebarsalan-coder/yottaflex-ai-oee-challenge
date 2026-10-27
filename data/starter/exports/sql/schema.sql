-- YottaFlex Industrial OEE Relational Schema (SQLite 3.x / ANSI SQL)
-- Strict primary keys, referential foreign keys, and domain enumeration constraints.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS plants (
    plant_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lines (
    line_id TEXT PRIMARY KEY,
    plant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    line_type TEXT NOT NULL CHECK (line_type IN ('MACHINING', 'ASSEMBLY', 'PACKAGING')),
    FOREIGN KEY (plant_id) REFERENCES plants(plant_id)
);

CREATE TABLE IF NOT EXISTS machines (
    machine_id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL,
    name TEXT NOT NULL,
    sequence_order INTEGER NOT NULL,
    criticality TEXT NOT NULL CHECK (criticality IN ('HIGH', 'MEDIUM', 'LOW')),
    FOREIGN KEY (line_id) REFERENCES lines(line_id)
);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    family TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shifts (
    shift_id TEXT PRIMARY KEY,
    plant_id TEXT NOT NULL,
    shift_code TEXT NOT NULL CHECK (shift_code IN ('SHIFT_A', 'SHIFT_B', 'SHIFT_C')),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    planned_break_sec INTEGER NOT NULL,
    FOREIGN KEY (plant_id) REFERENCES plants(plant_id)
);

CREATE TABLE IF NOT EXISTS machine_product_standards (
    standard_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    ideal_cycle_time_sec REAL NOT NULL,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS downtime_reasons (
    reason_code TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN ('PLANNED', 'UNPLANNED', 'CHANGEOVER', 'LINE_STOP')),
    description TEXT NOT NULL,
    affects_availability INTEGER NOT NULL CHECK (affects_availability IN (0, 1))
);

CREATE TABLE IF NOT EXISTS production_orders (
    order_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    target_quantity INTEGER NOT NULL,
    scheduled_start TEXT NOT NULL,
    scheduled_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PLANNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    planned_cycle_time_sec REAL NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (line_id) REFERENCES lines(line_id)
);

CREATE TABLE IF NOT EXISTS state_events (
    event_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    order_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('RUNNING', 'UNPLANNED_DOWNTIME', 'PLANNED_DOWNTIME', 'CHANGEOVER', 'STARVED', 'BLOCKED', 'OFF')),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    reason_code TEXT,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (shift_id) REFERENCES shifts(shift_id),
    FOREIGN KEY (order_id) REFERENCES production_orders(order_id)
);

CREATE TABLE IF NOT EXISTS production_counts (
    count_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    count_delta INTEGER NOT NULL,
    cumulative_count INTEGER NOT NULL,
    is_correction INTEGER NOT NULL CHECK (is_correction IN (0, 1)),
    correction_ref_id TEXT,
    FOREIGN KEY (order_id) REFERENCES production_orders(order_id),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (shift_id) REFERENCES shifts(shift_id),
    FOREIGN KEY (correction_ref_id) REFERENCES production_counts(count_id)
);

CREATE TABLE IF NOT EXISTS quality_inspections (
    inspection_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    shift_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    inspection_type TEXT NOT NULL CHECK (inspection_type IN ('FIRST_PIECE', 'IN_PROCESS', 'FINAL')),
    inspected_qty INTEGER NOT NULL,
    passed_qty INTEGER NOT NULL,
    scrap_qty INTEGER NOT NULL,
    rework_qty INTEGER NOT NULL,
    defect_code TEXT CHECK (defect_code IS NULL OR defect_code = '' OR defect_code IN ('DIMENSIONAL_OUT_OF_SPEC', 'SURFACE_SCRATCH', 'BURR_CONTAMINATION', 'MATERIAL_VOIDS', 'PACKAGING_DAMAGE', 'TOOL_MARKING')),
    FOREIGN KEY (order_id) REFERENCES production_orders(order_id),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (shift_id) REFERENCES shifts(shift_id)
);

CREATE TABLE IF NOT EXISTS oee_aggregates (
    aggregate_id TEXT PRIMARY KEY,
    shift_id TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    planned_prod_time_sec INTEGER NOT NULL,
    operating_time_sec INTEGER NOT NULL,
    unplanned_downtime_sec INTEGER NOT NULL,
    planned_downtime_sec INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    good_count INTEGER NOT NULL,
    scrap_count INTEGER NOT NULL,
    rework_count INTEGER NOT NULL,
    ideal_cycle_time_sec REAL NOT NULL,
    availability REAL NOT NULL,
    performance REAL NOT NULL,
    quality REAL NOT NULL,
    oee REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('CLEAN', 'FLAGGED', 'ANOMALOUS')),
    exception_count INTEGER NOT NULL,
    FOREIGN KEY (shift_id) REFERENCES shifts(shift_id),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
    FOREIGN KEY (line_id) REFERENCES lines(line_id)
);
