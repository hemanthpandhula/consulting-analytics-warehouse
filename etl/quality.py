"""Data-quality recorder: every rule reports rows checked, rows failed and what was done about them."""
import json
from dataclasses import dataclass, field


@dataclass
class DQ:
    rules: dict = field(default_factory=dict)
    quarantine: list = field(default_factory=list)   # (source_table, reason_code, row_json)

    def define(self, rule_id, table, description, action, severity="warning"):
        self.rules[rule_id] = {"rule_id": rule_id, "table": table, "description": description, "action": action,
                               "severity": severity, "checked": 0, "failed": 0, "status": "info"}

    def hit(self, rule_id, failed=False):
        r = self.rules[rule_id]
        r["checked"] += 1
        if failed:
            r["failed"] += 1

    def reject(self, rule_id, table, row):
        self.quarantine.append((table, rule_id, json.dumps(row, default=str)))

    def set_result(self, rule_id, checked, failed):
        r = self.rules[rule_id]
        r["checked"], r["failed"] = checked, failed
        r["status"] = "pass" if failed == 0 else "FAIL"

    def quarantined(self, table):
        return sum(1 for q in self.quarantine if q[0] == table)
