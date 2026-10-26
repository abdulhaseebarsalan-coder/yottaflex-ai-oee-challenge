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
        """Compare detected validator findings against ground truth anomalies."""
        evaluations: List[AnomalyDetectionEvaluation] = []
        matched_finding_indices: Set[int] = set()

        tp = 0
        fn = 0

        # Group detections by anomaly type
        detection_by_type: Dict[str, Dict[str, Any]] = {}

        for gt in self.ground_truth:
            anom_id = gt["anomaly_id"]
            anom_type = gt["anomaly_type"]
            tbl = gt["table_name"]
            rec_id = gt["record_id"]
            rel_rec_id = gt.get("related_record_id", "")
            exp_rule = gt["detection_rule_id"]

            matching_msgs = []
            is_detected = False

            for idx, finding in enumerate(findings):
                f_tbl = finding.get("table_name", "").replace(".csv", "")
                gt_tbl = tbl.replace(".csv", "")
                f_rec = str(finding.get("record_id", ""))
                f_rule = str(finding.get("rule_id", ""))

                # Match condition:
                # 1. Matching rule ID
                # 2. Matching table name
                # 3. Matching primary record_id OR related_record_id (for temporal overlaps)
                rule_match = (f_rule == exp_rule)
                table_match = (f_tbl == gt_tbl)
                record_match = (f_rec == rec_id or (rel_rec_id and f_rec == rel_rec_id))

                if rule_match and table_match and record_match:
                    is_detected = True
                    matching_msgs.append(finding.get("message", ""))
                    matched_finding_indices.add(idx)

            if is_detected:
                tp += 1
            else:
                fn += 1

            evaluations.append(
                AnomalyDetectionEvaluation(
                    anomaly_id=anom_id,
                    anomaly_type=anom_type,
                    target_table=tbl,
                    target_record_id=rec_id,
                    expected_rule_id=exp_rule,
                    detected=is_detected,
                    matching_findings_count=len(matching_msgs),
                    matching_finding_messages=matching_msgs,
                )
            )

            # Update anomaly type summary
            if anom_type not in detection_by_type:
                detection_by_type[anom_type] = {"total": 0, "detected": 0}
            detection_by_type[anom_type]["total"] += 1
            if is_detected:
                detection_by_type[anom_type]["detected"] += 1

        # False positives: findings that did not match any ground truth anomaly
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
