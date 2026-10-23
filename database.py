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

FACET_COLUMNS = ('property_type', 'compound', 'developer', 'location')
def get_distinct_facets():
    """Return sorted unique non-empty values for common search dimensions."""
    facets = {}
    with closing(connect()) as conn:
        for column in FACET_COLUMNS:
            rows = conn.execute(
                f'SELECT DISTINCT {column} FROM properties '
                f'WHERE {column} IS NOT NULL AND TRIM({column}) != \'\' '
                f'ORDER BY {column} COLLATE NOCASE'
            )
            facets[column] = [row[0] for row in rows]
    return facets

# print(get_distinct_facets()['property_type'])
# print("--------------------------------")
# print(get_distinct_facets()['compound'])
# print("--------------------------------")
# print(get_distinct_facets()['developer'])
# print("--------------------------------")
# print(get_distinct_facets()['location'])    



def inventory_summary():
    """Read current listing coverage and EGP bounds without caching or writes."""
    with closing(sqlite3.connect(DB_PATH.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, location, parent_location, property_type, finishing, updated_at,
                   COALESCE(min_price, price) AS low,
                   COALESCE(max_price, price) AS high,
                   EXISTS (SELECT 1 FROM json_each(payment_plans) plan
                           WHERE json_extract(plan.value, '$.currency') = 'EGP') AS is_egp
            FROM properties WHERE on_sale = 1 OR on_sale IS NULL
        """).fetchall()

    def bucket():
        return {'listing_count': 0, 'priced_egp_count': 0, 'min_price_egp': None, 'max_price_egp': None}

    def add(group, row):
        group['listing_count'] += 1
        if row['is_egp'] and row['low'] is not None and row['high'] is not None and row['low'] > 0 and row['high'] >= row['low']:
            group['priced_egp_count'] += 1
            group['min_price_egp'] = row['low'] if group['min_price_egp'] is None else min(group['min_price_egp'], row['low'])
            group['max_price_egp'] = row['high'] if group['max_price_egp'] is None else max(group['max_price_egp'], row['high'])

    overall, areas, types = bucket(), {}, {}
    for row in rows:
        add(overall, row)
        kind = row['property_type'] or 'Unknown'
        add(types.setdefault(kind, bucket()), row)
        # Parent area buckets include their neighborhoods, just like local search.
        names = {name.strip() for name in (row['location'], row['parent_location']) if name and name.strip()}
        for name in names:
            area = areas.setdefault(name, {**bucket(), 'property_types': {}})
            add(area, row)
            add(area['property_types'].setdefault(kind, bucket()), row)
    return {
        'status': 'ok', 'source': 'local_sqlite',
        'scope': 'Stored listings only, not market-wide availability. Area totals may overlap through parent areas.',
        'last_listing_update': max((row['updated_at'] for row in rows), default=None),
        'overall': overall, 'property_types': dict(sorted(types.items())),
        'finishing_options': sorted({row['finishing'] for row in rows if row['finishing']}),
        'locations': dict(sorted(areas.items())),
    }
