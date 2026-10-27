"""Separate benchmark component comparing validator findings against ground truth anomalies."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class AnomalyDetectionEvaluation:
    """Detection performance status for an individual ground truth anomaly."""
    anomaly_id: str
    anomaly_type: str
    target_table: str
    target_record_id: str
    expected_rule_id: str
    detected: bool
    matching_findings_count: int
    matching_finding_messages: List[str]


@dataclass
class BenchmarkResult:
    """Consolidated benchmark scoring precision, recall, and detection accuracy."""
    total_ground_truth_anomalies: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    detection_by_type: Dict[str, Dict[str, Any]]
    evaluations: List[AnomalyDetectionEvaluation]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_ground_truth_anomalies": self.total_ground_truth_anomalies,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "detection_by_type": self.detection_by_type,
            "evaluations": [
                {
                    "anomaly_id": e.anomaly_id,
                    "anomaly_type": e.anomaly_type,
                    "target_table": e.target_table,
                    "target_record_id": e.target_record_id,
                    "expected_rule_id": e.expected_rule_id,
                    "detected": e.detected,
                    "matching_findings_count": e.matching_findings_count,
                    "matching_finding_messages": e.matching_finding_messages,
                }
                for e in self.evaluations
            ],
        }


class GroundTruthBenchmark:
    """Evaluates validation engine accuracy against external ground truth labels.
    
    GOVERNANCE NOTE: This class is the ONLY component permitted to consume
    ground_truth.json / ground_truth.csv. It must remain strictly separated
    from the production validation engine and OEE calculation engine.
    """

    def __init__(self, ground_truth_file: Path) -> None:
        self.ground_truth_file = ground_truth_file
        self.ground_truth = self._load_ground_truth()

    def _load_ground_truth(self) -> List[Dict[str, Any]]:
        """Load ground truth records from JSON."""
        if not self.ground_truth_file.exists():
            raise FileNotFoundError(f"Ground truth file not found: {self.ground_truth_file}")
        with open(self.ground_truth_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def evaluate(self, findings: List[Dict[str, Any]]) -> BenchmarkResult:
        """Compare detected validator findings against ground truth anomalies at the record level.
        
        Under record-level matching, any finding targeting an anomalous record is attributed
        as a detection for that anomaly. Multiple rules firing on the same anomalous record
        (e.g. scrap overflow and mass-balance, or state overlap and time accounting) are
        treated as companion detections, not false positives.
        """
        evaluations: List[AnomalyDetectionEvaluation] = []

        # Build lookup of all ground truth anomalous target records: (table, record_id) -> list of GT anomalies
        gt_by_record: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for gt in self.ground_truth:
            tbl = gt["table_name"].replace(".csv", "")
            rec_id = str(gt["record_id"])
            gt_by_record.setdefault((tbl, rec_id), []).append(gt)

            rel_rec = gt.get("related_record_id")
            if rel_rec and str(rel_rec).strip():
                gt_by_record.setdefault((tbl, str(rel_rec)), []).append(gt)

        # Map findings to matching ground truth anomalies
        detected_anom_ids: Set[str] = set()
        findings_by_anom_id: Dict[str, List[str]] = {gt["anomaly_id"]: [] for gt in self.ground_truth}
        matched_finding_indices: Set[int] = set()

        for idx, finding in enumerate(findings):
            f_tbl = str(finding.get("table_name", "")).replace(".csv", "")
            f_rec = str(finding.get("record_id", ""))
            f_key = (f_tbl, f_rec)

            if f_key in gt_by_record:
                matched_finding_indices.add(idx)
                for matched_gt in gt_by_record[f_key]:
                    anom_id = matched_gt["anomaly_id"]
                    detected_anom_ids.add(anom_id)
                    findings_by_anom_id[anom_id].append(
                        f"[{finding.get('rule_id')}] {finding.get('message', '')}"
                    )

        tp = 0
        fn = 0
        detection_by_type: Dict[str, Dict[str, Any]] = {}

        for gt in self.ground_truth:
            anom_id = gt["anomaly_id"]
            anom_type = gt["anomaly_type"]
            is_detected = anom_id in detected_anom_ids
            matching_msgs = findings_by_anom_id.get(anom_id, [])

            if is_detected:
                tp += 1
            else:
                fn += 1

            evaluations.append(
                AnomalyDetectionEvaluation(
                    anomaly_id=anom_id,
                    anomaly_type=anom_type,
                    target_table=gt["table_name"],
                    target_record_id=gt["record_id"],
                    expected_rule_id=gt["detection_rule_id"],
                    detected=is_detected,
                    matching_findings_count=len(matching_msgs),
                    matching_finding_messages=matching_msgs,
                )
            )

            if anom_type not in detection_by_type:
                detection_by_type[anom_type] = {"total": 0, "detected": 0}
            detection_by_type[anom_type]["total"] += 1
            if is_detected:
                detection_by_type[anom_type]["detected"] += 1

        # False positives: findings targeting records that have no injected anomalies
        fp = len(findings) - len(matched_finding_indices)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        return BenchmarkResult(
            total_ground_truth_anomalies=len(self.ground_truth),
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            precision=precision,
            recall=recall,
            f1_score=f1,
            detection_by_type=detection_by_type,
            evaluations=evaluations,
        )

