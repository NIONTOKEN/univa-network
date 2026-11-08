"""Small SQLite side-index for UNIVA testnet. Consensus remains the JSON chain file."""
import json
import hashlib
import sqlite3
import time
from pathlib import Path


def _connect(db_path="univa_chain.db"):
    path = Path(db_path)
    if path.parent and str(path.parent) not in (".", ""):
        path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
      CREATE TABLE IF NOT EXISTS blocks (
        height INTEGER PRIMARY KEY, hash TEXT NOT NULL UNIQUE,
        timestamp REAL NOT NULL, block_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS transactions (
        tx_id TEXT PRIMARY KEY, block_height INTEGER NOT NULL,
        tx_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS peers (
        peer_id TEXT PRIMARY KEY, host TEXT NOT NULL, port INTEGER NOT NULL,
        version TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        last_seen REAL NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_tx_height ON transactions(block_height);
      CREATE INDEX IF NOT EXISTS idx_peers_active ON peers(active);
    """)
    return con


def insert_block(block, db_path="univa_chain.db"):
    height = int(block["index"])
    with _connect(db_path) as con:
        con.execute("INSERT OR REPLACE INTO blocks(height,hash,timestamp,block_json) VALUES(?,?,?,?)",
                    (height, block["hash"], float(block["timestamp"]), json.dumps(block, sort_keys=True)))


def insert_transactions(block, db_path="univa_chain.db"):
    with _connect(db_path) as con:
        for tx in block.get("transactions", []):
            canonical = json.dumps(tx, sort_keys=True, separators=(",", ":"))
            tx_id = tx.get("tx_id") or hashlib.sha256(f"{block.get('index')}:{canonical}".encode()).hexdigest()
            con.execute("INSERT OR REPLACE INTO transactions(tx_id,block_height,tx_json) VALUES(?,?,?)",
                        (tx_id, int(block["index"]), json.dumps(tx, sort_keys=True)))


def upsert_peer(peer_id, host, port, version="?", db_path="univa_chain.db"):
    with _connect(db_path) as con:
        con.execute("""INSERT INTO peers(peer_id,host,port,version,active,last_seen) VALUES(?,?,?,?,1,?)
          ON CONFLICT(peer_id) DO UPDATE SET host=excluded.host,port=excluded.port,
          version=excluded.version,active=1,last_seen=excluded.last_seen""",
          (str(peer_id), str(host), int(port), str(version), time.time()))


def get_active_peers(db_path="univa_chain.db"):
    with _connect(db_path) as con:
        rows = con.execute("SELECT peer_id,host,port,version,last_seen FROM peers WHERE active=1 ORDER BY last_seen DESC").fetchall()
        return [dict(r) for r in rows]


def mark_peer_inactive(peer_id, db_path="univa_chain.db"):
    with _connect(db_path) as con:
        con.execute("UPDATE peers SET active=0,last_seen=? WHERE peer_id=?", (time.time(), str(peer_id)))


def get_median_time_past(n=11, db_path="univa_chain.db"):
    with _connect(db_path) as con:
        rows = con.execute("SELECT timestamp FROM blocks ORDER BY height DESC LIMIT ?", (int(n),)).fetchall()
    values = sorted(float(r[0]) for r in rows)
    return values[len(values)//2] if values else 0.0


def update_balance(address, amount, db_path="univa_chain.db"):
    # Deliberately no balance table: balances are derived from validated chain state.
    return None


def rebuild_index(chain, db_path="univa_chain.db"):
    """Rebuild the non-consensus SQLite index from validated in-memory chain data."""
    with _connect(db_path) as con:
        con.execute("DELETE FROM transactions")
        con.execute("DELETE FROM blocks")
        for block_obj in chain:
            block = block_obj.to_dict() if hasattr(block_obj, "to_dict") else block_obj
            con.execute("INSERT OR REPLACE INTO blocks(height,hash,timestamp,block_json) VALUES(?,?,?,?)",
                        (int(block["index"]), block["hash"], float(block["timestamp"]), json.dumps(block, sort_keys=True)))
            for tx in block.get("transactions", []):
                canonical = json.dumps(tx, sort_keys=True, separators=(",", ":"))
                tx_id = tx.get("tx_id") or hashlib.sha256(f"{block.get('index')}:{canonical}".encode()).hexdigest()
                con.execute("INSERT OR REPLACE INTO transactions(tx_id,block_height,tx_json) VALUES(?,?,?)",
                            (tx_id, int(block["index"]), json.dumps(tx, sort_keys=True)))
