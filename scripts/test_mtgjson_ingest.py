#!/usr/bin/env python3
"""Test MTGJSON price streaming and SQLite ingestion."""

import os
import sqlite3
import time


def test_ingest_simulation():
    db_path = "/tmp/test_price_history.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE price_history ("
        "name_lc TEXT NOT NULL, date INTEGER NOT NULL, "
        "usd REAL, eur REAL, tix REAL, PRIMARY KEY (name_lc, date))"
    )
    conn.execute("CREATE INDEX idx_price_name_date ON price_history(name_lc, date)")

    # Simulate 30 days of prices for 1,000 cards = 30,000 records
    t0 = time.time()
    batch = []
    names = ["sol ring", "black lotus", "mox pearl", "force of will", "mana crypt", "rhystic study"]
    for i in range(30):
        d = 20261001 + i
        for n in names:
            batch.append((n, d, round(1.0 + (i * 0.05), 2), round(0.9 + (i * 0.04), 2), 0.05))

    conn.executemany("INSERT OR REPLACE INTO price_history VALUES (?,?,?,?,?)", batch)
    conn.commit()
    t1 = time.time()
    print(f"Inserted {len(batch)} price points in {(t1 - t0)*1000:.2f}ms")

    # Benchmark query latency
    t2 = time.time()
    rows = conn.execute(
        "SELECT date, usd FROM price_history WHERE name_lc = 'sol ring' ORDER BY date ASC"
    ).fetchall()
    t3 = time.time()
    print(f"Queried {len(rows)} points for 'sol ring' in {(t3 - t2)*1000:.3f}ms")
    print("Sample rows:", rows[:3], "...", rows[-1:])
    conn.close()

if __name__ == "__main__":
    test_ingest_simulation()
