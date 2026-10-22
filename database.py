"""SQLite storage for normalized properties and resumable scraping."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / 'data' / 'nawy.db'
TEXT_FIELDS = ('url', 'name', 'property_type', 'compound', 'developer', 'location',
               'parent_location', 'finishing', 'delivery_date', 'description', 'image_url')
NUMBER_FIELDS = ('price', 'min_price', 'max_price', 'area_m2', 'max_area_m2', 'bedrooms', 'bathrooms')
BOOL_FIELDS = ('resale', 'on_sale')
JSON_FIELDS = ('amenities', 'payment_plans')
FIELDS = ('id',) + TEXT_FIELDS + NUMBER_FIELDS + BOOL_FIELDS + JSON_FIELDS


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    columns = ['id INTEGER PRIMARY KEY']
    columns += [f'{key} TEXT' for key in TEXT_FIELDS + JSON_FIELDS]
    columns += [f'{key} REAL' for key in NUMBER_FIELDS]
    columns += [f'{key} INTEGER CHECK ({key} IN (0, 1))' for key in BOOL_FIELDS]
    columns += ['updated_at TEXT NOT NULL']
    with closing(connect()) as conn, conn:
        conn.execute('CREATE TABLE IF NOT EXISTS properties (' + ', '.join(columns) + ')')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_properties_location_price ON properties(location, price)')
        conn.execute('CREATE TABLE IF NOT EXISTS scrape_state (id INTEGER PRIMARY KEY CHECK(id = 1), data TEXT NOT NULL)')


def _upsert(conn, prop, timestamp):
    unknown = set(prop) - set(FIELDS)
    if unknown:
        raise ValueError(f'Unrecognized property fields: {sorted(unknown)}')
    values = [json.dumps(prop[key], ensure_ascii=False) if key in JSON_FIELDS and key in prop
              else prop.get(key) for key in FIELDS]
    columns = FIELDS + ('updated_at',)
    conn.execute(
        f"INSERT INTO properties ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
        'ON CONFLICT(id) DO UPDATE SET ' + ', '.join(f'{key}=excluded.{key}' for key in columns if key != 'id'),
        values + [timestamp],
    )


def save_checkpoint(state, property_record=None):
    """Commit a new unit and its progress together, or just update progress."""
    timestamp = datetime.now(timezone.utc).isoformat()
    metadata = {k: v for k, v in state.items() if k != 'properties'}
    metadata['updated_at'] = timestamp
    with closing(connect()) as conn, conn:
        if property_record is not None:
            _upsert(conn, property_record, timestamp)
        metadata['scraped_count'] = conn.execute('SELECT COUNT(*) FROM properties').fetchone()[0]
        conn.execute('INSERT INTO scrape_state VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                     (json.dumps(metadata, ensure_ascii=False),))


def get_property_ids():
    """Read only IDs for fast duplicate checks before requesting detail pages."""
    with closing(connect()) as conn:
        return {str(row[0]) for row in conn.execute("SELECT id FROM properties")}


def load_checkpoint(ids_only=False):
    with closing(connect()) as conn:
        row = conn.execute('SELECT data FROM scrape_state WHERE id=1').fetchone()
        state = json.loads(row['data']) if row else {}
        properties = []
        query = 'SELECT id FROM properties ORDER BY id' if ids_only else 'SELECT * FROM properties ORDER BY id'
        for row in conn.execute(query):
            prop = {key: row[key] for key in row.keys() if key in FIELDS and row[key] is not None}
            for key in JSON_FIELDS:
                if key in prop:
                    prop[key] = json.loads(prop[key])
            for key in BOOL_FIELDS:
                if key in prop:
                    prop[key] = bool(prop[key])
            properties.append(prop)
        state['properties'] = properties
        return state


def import_json(path):
    """One-time, atomic import; reruns never overwrite newer database records."""
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    properties = payload['properties']
    timestamp = payload.get('updated_at') or payload.get('scraped_at') or datetime.now(timezone.utc).isoformat()
    metadata = {k: v for k, v in payload.items() if k != 'properties'}
    init_db()
    with closing(connect()) as conn, conn:
        for prop in properties:
            if conn.execute('SELECT 1 FROM properties WHERE id=?', (prop['id'],)).fetchone() is None:
                _upsert(conn, prop, timestamp)
        metadata['scraped_count'] = conn.execute('SELECT COUNT(*) FROM properties').fetchone()[0]
        conn.execute('INSERT OR IGNORE INTO scrape_state VALUES (1, ?)', (json.dumps(metadata, ensure_ascii=False),))
    return len(properties)
