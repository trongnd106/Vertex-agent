"""Minimal CSV summary helper for the data-analysis skill.

Usage:
    python scripts/analyze.py <path-to-csv>

Prints per-column stats (count / mean / min / max) for numeric columns and
value-counts for the first non-numeric column. Pure stdlib, no dependencies.
"""

from __future__ import annotations

import csv
import statistics
import sys


def summarize(path: str) -> None:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("Empty CSV: no data rows.")
        return

    columns = list(rows[0])
    print(f"rows={len(rows)} columns={len(columns)}")
    numeric_by_column: dict[str, list[float]] = {c: [] for c in columns}
    for row in rows:
        for col in columns:
            raw = (row.get(col) or "").strip().replace(",", "")
            try:
                numeric_by_column[col].append(float(raw))
            except ValueError:
                pass

    for col in columns:
        values = numeric_by_column[col]
        if values:
            print(
                f"{col}: count={len(values)} mean={statistics.mean(values):.4f} "
                f"min={min(values)} max={max(values)}"
            )
        else:
            counts: dict[str, int] = {}
            for row in rows:
                counts[row.get(col, "")] = counts.get(row.get(col, ""), 0) + 1
            top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
            print(f"{col}: categorical -> {dict(top)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__ + "Truyền đúng 1 đối số: path tới file CSV.")
    summarize(sys.argv[1])