"""SQLite sidecar: build, status, open, legacy JSONL loader, DB query helpers.

The JSONL stays canonical; this DB is a derived, rebuildable index. Reads the
shared state from `state` (DB, DB_MODE, FORCE_NO_DB, CARDS, paths) — it is the
only module allowed to *write* DB/DB_MODE/CARDS after startup.
"""
import json
import os
import sys
import time

from . import state
from .project import slim_card
from .state import ORACLE_PATH, DB_PATH, SCHEMA_VERSION, warn

# ── SQLite sidecar (Option C, design doc §3) ────────────────────────────
# The JSONL stays canonical; this DB is a derived, rebuildable index.
# Stored `data` is exactly the slim_card() projection, so every output layer
# (display, json/jsonl/csv/tsv) sees what the JSONL path gives it. One field
# the filters need — color_identity — is NOT in slim_card() output, so it is
# promoted into its own indexed table rather than smuggled into `data`
# (which would change machine-mode output and break parity).


def _sqlite_module():
    try:
        import sqlite3
        return sqlite3
    except ImportError:
        return None

def _sqlite_supports_fts5(sq):
    """True only if fts5 AND the trigram tokenizer both work in this build."""
    if sq is None:
        return False
    try:
        probe = sq.connect(":memory:")
        try:
            probe.execute("CREATE VIRTUAL TABLE _p USING fts5(x, tokenize='trigram')")
            return True
        finally:
            probe.close()
    except Exception:
        return False

def _fts_phrase(term):
    """Escape a user substring for use as a single trigram MATCH phrase."""
    return '"' + term.replace('"', '""') + '"'

def db_status():
    """Return (stale, reason) for the sidecar. Missing counts as stale."""
    if not os.path.exists(DB_PATH):
        return True, "missing"
    sq = _sqlite_module()
    if sq is None:
        return True, "sqlite3 unavailable"
    try:
        conn = sq.connect(DB_PATH)
        try:
            meta = dict(conn.execute("SELECT k, v FROM meta").fetchall())
        finally:
            conn.close()
    except Exception as e:
        return True, "unreadable (%s)" % e
    if meta.get("schema_version") != SCHEMA_VERSION:
        return True, "schema version %r (expected %r)" % (meta.get("schema_version"), SCHEMA_VERSION)
    try:
        st = os.stat(ORACLE_PATH)
    except OSError:
        return True, "source jsonl missing"
    if float(meta.get("source_mtime", -1)) != st.st_mtime:
        return True, "source mtime changed"
    if int(meta.get("source_size", -1)) != st.st_size:
        return True, "source size changed"
    return False, "fresh"

def build_db(verbose=True):
    """Build the sidecar from ORACLE_PATH: temp file + atomic swap.

    Concurrency (design doc §3, "swap-if-still-absent"): a best-effort O_EXCL
    lock stops parallel callers all burning a build. A caller that loses the
    race waits briefly, then uses whatever appeared or proceeds regardless —
    readers never see a partial state.DB because os.replace() swaps in a finished file.
    """
    import time
    sq = _sqlite_module()
    if sq is None:
        warn("sqlite3 is not available; cannot build index")
        return False
    cache_dir = os.path.dirname(DB_PATH)
    os.makedirs(cache_dir, exist_ok=True)
    lock_path = DB_PATH + ".lock"
    tmp_path = "%s.build.%d.tmp" % (DB_PATH, os.getpid())

    got_lock = False
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        got_lock = True
    except FileExistsError:
        for _ in range(80):                      # up to ~20 s
            time.sleep(0.25)
            stale, _why = db_status()
            if not stale:
                if verbose:
                    warn("index build already running elsewhere; using completed DB")
                return True
            if not os.path.exists(lock_path):
                break                            # previous builder died; take over
        else:
            warn("timed out waiting for another build; proceeding anyway")
    except OSError as e:
        warn("could not create lock (%s); building without it" % e)

    try:
        st = os.stat(ORACLE_PATH)
        conn = sq.connect(tmp_path)
        try:
            conn.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")
            conn.execute("CREATE TABLE cards(rid INTEGER PRIMARY KEY, name TEXT,"
                         " name_lc TEXT NOT NULL, cmc REAL, lang TEXT, data TEXT NOT NULL)")
            conn.execute("CREATE VIRTUAL TABLE cards_ft USING fts5("
                         "name, oracle_text, type_line, tokenize='trigram')")
            conn.execute("CREATE TABLE colors(rid INTEGER NOT NULL, color TEXT NOT NULL)")

            rows, ft_rows, color_rows = [], [], []
            n = 0
            with open(ORACLE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    n += 1                       # rid == JSONL line order (§3)
                    s = slim_card(raw)
                    rows.append((n, s.get("name"), (s.get("name") or "").lower(),
                                 s.get("cmc"), s.get("lang", "en"),
                                 json.dumps(s, ensure_ascii=False)))
                    ft_rows.append((n, s.get("name") or "", s.get("oracle_text") or "",
                                    s.get("type_line") or ""))
                    # color_identity read from RAW: slim_card drops it, but
                    # search_color and --commander filter on it.
                    for col in (raw.get("color_identity") or []):
                        color_rows.append((n, col))

            conn.executemany("INSERT INTO cards VALUES(?,?,?,?,?,?)", rows)
            conn.executemany("INSERT INTO cards_ft(rowid,name,oracle_text,type_line)"
                             " VALUES(?,?,?,?)", ft_rows)
            conn.executemany("INSERT INTO colors VALUES(?,?)", color_rows)
            conn.execute("INSERT INTO meta VALUES('schema_version',?)", (SCHEMA_VERSION,))
            conn.execute("INSERT INTO meta VALUES('source_mtime',?)", (str(st.st_mtime),))
            conn.execute("INSERT INTO meta VALUES('source_size',?)", (str(st.st_size),))
            conn.execute("INSERT INTO meta VALUES('row_count',?)", (str(n),))
            conn.commit()
            for idx in ("CREATE INDEX cards_name_lc ON cards(name_lc)",
                        "CREATE INDEX cards_cmc ON cards(cmc)",
                        "CREATE INDEX colors_color ON colors(color)"):
                conn.execute(idx)
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp_path, DB_PATH)
        if verbose:
            warn("✓ index built: %s cards, %.1f MB" %
                 (format(n, ","), os.path.getsize(DB_PATH) / (1024 * 1024)))
        return True
    except Exception as e:
        warn("index build failed: %s (using JSONL scan instead)" % e)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False
    finally:
        if got_lock:
            try:
                os.remove(lock_path)
            except OSError:
                pass

def open_db():
    """Open the sidecar for reading. Returns a connection or None."""
    sq = _sqlite_module()
    if sq is None or not _sqlite_supports_fts5(sq):
        return None
    try:
        conn = sq.connect(DB_PATH)
        conn.execute("PRAGMA query_only = ON")
        return conn
    except Exception as e:
        warn("could not open index (%s); using JSONL scan instead" % e)
        return None


def check_cache_age():
    """Warn on stderr if the JSONL cache is older than 30 days."""
    if getattr(state, "_CACHE_AGE_WARNED", False):
        return
    state._CACHE_AGE_WARNED = True
    if os.environ.get("SCRYFALL_NO_CACHE_WARN"):
        return
    if not os.path.exists(ORACLE_PATH):
        return
    try:
        mtime = os.stat(ORACLE_PATH).st_mtime
        age_days = int((time.time() - mtime) / 86400)
        if age_days > 30:
            warn(f"card cache is {age_days} days old — run 'scryfall update' to refresh")
    except OSError:
        pass


def load_cards():
    """Ensure card data is available.

    Preferred path (Option C): a fresh SQLite sidecar, opened read-only — no
    full parse, so startup costs an indexed query instead of ~1.3 s of JSON.
    Fallback: the original whole-file JSONL scan, used verbatim whenever the
    index is missing/stale/corrupt/unbuildable or --no-db was passed. The
    fallback never regresses behaviour; it is just slower.
    """
    check_cache_age()
    if state.DB_MODE and state.DB is not None:
        return
    if state.CARDS:
        return
    if not os.path.exists(ORACLE_PATH):
        print(f"Error: Oracle cards file not found at {ORACLE_PATH}", file=sys.stderr)
        print("Run the Scryfall cache update first.", file=sys.stderr)
        sys.exit(1)

    if not state.FORCE_NO_DB:
        sq = _sqlite_module()
        if sq is not None and _sqlite_supports_fts5(sq):
            stale, reason = db_status()
            if stale and reason == "missing":
                build_db(verbose=True)            # transparent one-time build
                stale, reason = db_status()
            if not stale:
                conn = open_db()
                if conn is not None:
                    state.DB = conn
                    state.DB_MODE = True
                    return
        # sqlite absent / fts5 absent / stale-and-present / open failed → legacy
    _load_cards_jsonl()

def _load_cards_jsonl():
    """Legacy path: parse every line of the cache into CARDS."""
    state.CARDS = []
    with open(ORACLE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    state.CARDS.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

# ── DB query helpers ────────────────────────────────────────────────────
def _hydrate(rows):
    """Turn rows of ('data' column) into card dicts, preserving row order."""
    return [json.loads(r[0]) for r in rows]

def _like_pattern(q):
    """LIKE pattern for a true substring match, with % and _ escaped."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

# Columns promoted to real table columns, for the sub-3-char LIKE fallback path.
# cards_ft column -> cards column (None = no cheap column, scan data instead).
_FT_TO_COL = {"name": "name_lc"}

def _substr_rows(ft_column, query):
    """Rows matching `query` as a true substring of one FTS-indexed field.

    Length-gated router (design doc §3.3): the trigram tokenizer needs >= 3
    characters and SILENTLY returns zero rows below that — measured on this
    cache, "a" gives 29,707 LIKE matches vs 0 from trigram, "so" 1,199 vs 0,
    "ri" 5,302 vs 0. So short queries must take the LIKE path, never FTS.
    """
    q = query.lower()
    if len(q) >= 3:
        sql = ("SELECT c.data FROM cards c JOIN cards_ft f ON f.rowid = c.rid"
               " WHERE f.%s MATCH ? ORDER BY c.rid" % ft_column)
        return state.DB.execute(sql, (_fts_phrase(q),)).fetchall()
    col = _FT_TO_COL.get(ft_column)
    if col:
        sql = "SELECT data FROM cards WHERE %s LIKE ? ESCAPE '\\' ORDER BY rid" % col
        return state.DB.execute(sql, (_like_pattern(q),)).fetchall()
    # No promoted column for this field (oracle_text/type_line): fall back to a
    # JSON-extract scan, which is still one pass, not 38k parses.
    key = {"oracle_text": "$.oracle_text", "type_line": "$.type_line"}[ft_column]
    sql = ("SELECT data FROM cards"
           " WHERE lower(json_extract(data, '%s')) LIKE ? ESCAPE '\\' ORDER BY rid" % key)
    return state.DB.execute(sql, (_like_pattern(q),)).fetchall()

def _any_substr_rows(query):
    """Rows whose name OR oracle text OR type line contains `query`."""
    q = query.lower()
    if len(q) >= 3:
        sql = ("SELECT c.data FROM cards c JOIN cards_ft f ON f.rowid = c.rid"
               " WHERE cards_ft MATCH ? ORDER BY c.rid")
        return state.DB.execute(sql, (_fts_phrase(q),)).fetchall()
    sql = ("SELECT data FROM cards WHERE name_lc LIKE :p ESCAPE '\\'"
           " OR lower(json_extract(data, '$.oracle_text')) LIKE :p ESCAPE '\\'"
           " OR lower(json_extract(data, '$.type_line')) LIKE :p ESCAPE '\\'"
           " ORDER BY rid")
    return state.DB.execute(sql, {"p": _like_pattern(q)}).fetchall()
