#!/usr/bin/env python3
"""Export final results from checkpoint DB, mocking unprocessed URLs as errors."""

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "checkpoints" / "checkpoint.db"
INPUT_CSV = BASE_DIR / "data" / "ifood_urls_padrao_item_1000.csv"
OUTPUT_DIR = BASE_DIR / "output"


def _format_brl(value):
    if value is None:
        return None
    int_part, frac_part = f"{value:.2f}".split(".")
    int_part = "{:,}".format(int(int_part)).replace(",", ".")
    return f"R$ {int_part},{frac_part}"


def read_all_urls(path: Path) -> list[str]:
    urls = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        first = next(reader, None)
        if not first:
            return urls
        col = 0
        if any("url" in c.lower() for c in first):
            for i, h in enumerate(first):
                if "url" in h.lower():
                    col = i
                    break
        else:
            urls.append(first[col].strip())
        for row in reader:
            if row and len(row) > col and row[col].strip():
                urls.append(row[col].strip())
    return urls


def load_db_results(db_path: Path) -> dict[str, dict]:
    results = {}
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT * FROM crawl_results").fetchall()
        for r in rows:
            results[r[0]] = {
                "title": r[1],
                "normal_price": r[2],
                "discount_price": r[3],
                "image_url": r[4],
                "status": r[5],
                "error_message": r[6],
                "attempt": r[7],
                "duration_ms": r[8],
                "recovered": bool(r[9]) if r[9] is not None else False,
                "timestamp": r[10],
            }
    return results


def make_output_dict(url: str, db_row: dict | None, now: str) -> dict:
    if db_row:
        return {
            "title": db_row["title"],
            "normal_price": _format_brl(db_row["normal_price"]),
            "discount_price": _format_brl(db_row["discount_price"]),
            "product_url": url,
            "image_url": db_row["image_url"],
            "status": db_row["status"],
            "error_message": db_row["error_message"],
        }
    else:
        return {
            "title": None,
            "normal_price": None,
            "discount_price": None,
            "product_url": url,
            "image_url": None,
            "status": "error",
            "error_message": "URL nao processada (crawler nao completou todas as URLs)",
        }


def main():
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    all_urls = read_all_urls(INPUT_CSV)
    db_results = load_db_results(DB_PATH)

    print(f"Input CSV: {len(all_urls)} URLs")
    print(f"DB: {len(db_results)} resultados ({sum(1 for v in db_results.values() if v['status']=='success')} success, {sum(1 for v in db_results.values() if v['status']=='error')} error)")
    print(f"Missing: {len(all_urls) - len(db_results)} URLs nao processadas")

    output_rows = []
    for url in all_urls:
        output_rows.append(make_output_dict(url, db_results.get(url), now))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT_DIR / "results.csv"
    json_path = OUTPUT_DIR / "results.json"

    fields = ["title", "normal_price", "discount_price", "product_url", "image_url", "status", "error_message"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"CSV: {csv_path} ({len(output_rows)} linhas)")

    json_path.write_text(json.dumps(output_rows, indent=2, ensure_ascii=False))
    print(f"JSON: {json_path} ({len(output_rows)} registros)")


if __name__ == "__main__":
    main()
