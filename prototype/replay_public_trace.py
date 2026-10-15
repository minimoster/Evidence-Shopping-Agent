"""Offline rule replay of captured public observations, not a live shopping agent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import EvidenceLedger, parse_query, verify_purchase

ROOT = Path(__file__).resolve().parents[1]
# Hand-authored narrow-grammar integration scenario. Not an original benchmark task.
SCENARIO_QUERY = "标题:高档Gululu Q智能语音水杯保温杯儿童316不锈钢可爱;预算:不超过1490元"
SCENARIO_ASIN = "713372262998"


def replay(trace_path: Path) -> dict:
    rows = json.loads(trace_path.read_text(encoding="utf-8"))
    requirements = parse_query(SCENARIO_QUERY)
    ledger = EvidenceLedger()
    output = []
    for row in rows:
        public = row["observation"]
        snapshot = ledger.ingest(public)
        decision = verify_purchase(requirements, ledger, intended_asin=SCENARIO_ASIN,
                                   intended_options=public.get("selected_options", {}))
        output.append({"captured_action": row["action"], "snapshot": snapshot.to_dict(),
                       "decision": decision.to_dict()})
    return {
        "kind": "offline-public-state-rule-replay-not-agent-or-RL-evaluation",
        "requirements_source": "hand-authored narrow-grammar integration scenario, not original simulator task",
        "requirements": requirements.to_dict(),
        "actual_actions_executed_by_this_script": 0,
        "claims_simulator_task_success": False,
        "steps": output,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=ROOT / "results/public_simulator_trace.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(replay(args.trace), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
