from __future__ import annotations
import json
from pathlib import Path
from atlas.staging import StagingReadiness

root=Path(__file__).resolve().parent
(root/'runtime').mkdir(exist_ok=True)
(root/'runtime'/'leads.jsonl').touch(exist_ok=True)
report=StagingReadiness.inspect(root)
print(json.dumps(report.to_dict(), indent=2))
raise SystemExit(0 if report.code_ready else 2)
