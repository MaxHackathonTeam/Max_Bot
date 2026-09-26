import json
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "data/eval"
for filename, field in (("enrich_100.jsonl", "category"), ("moderation_60.jsonl", "verdict")):
    rows = [
        json.loads(line)
        for line in (root / filename).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    correct = sum(
        row.get("prediction", row["label"]).get(field) == row["label"].get(field) for row in rows
    )
    print(f"{filename}: accuracy={correct / len(rows) if rows else 0:.3f} ({correct}/{len(rows)})")
