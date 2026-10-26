"""Direct API response storage for MasterV, using DataId for upserts."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'data' / 'masterv.db'
CITIES = {
    1: 'New Cairo', 2: 'New Capital', 3: 'Al-Mostakbal',
    4: 'Al-Shorouk', 5: '6th October', 6: 'North Coast', 7: 'Ain Sokhna',
}
FIELD_MAP = {
    'data_id': 'DataId', 'compound_id': 'DataCompoundId', 'city_id': 'DataCityId',
    'name': 'DataCompound', 'name_ar': 'DataCompoundAr',
    'developer_id': 'DataDeveloperId', 'developer_name': 'DataDeveloper',
    'developer_name_ar': 'DataDeveloperAr', 'area_id': 'DataAreaId',
    'area_name': 'DataArea', 'area_name_ar': 'DataAreaAr',
    'coordinates': 'DataCoordinates', 'project_area': 'DataAcres_ProjectArea',
    'bedrooms': 'DataBedRooms', 'min_unit_price': 'DataMinUnitPrice',
    'min_built_up_area': 'DataMinBuiltUpAreaFrom', 'finishing': 'DataFinishing',
}


def save_city(city, results, collected_at, db_path=DB_PATH):
    """Validate and upsert one API response directly, atomically per city."""
    if city not in CITIES or not isinstance(results, list):
        raise ValueError('Invalid city or results.')
    imported_at = datetime.now(timezone.utc).isoformat()
    records, seen = [], set()
    for record in results:
        if not isinstance(record, dict) or record.get('DataCityId') != city:
            raise ValueError(f'City {city} contains a mismatched record.')
        key = record.get('DataId')
        if type(key) is not int or key in seen:
            raise ValueError('Missing, invalid or duplicate DataId.')
        seen.add(key)
        values = [record.get(source) for source in FIELD_MAP.values()]
        source_date = record.get('DataDate')
        values += [source_date.get('Date') if isinstance(source_date, dict) else None,
                   json.dumps(record, ensure_ascii=False), collected_at, imported_at]
        records.append(values)
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript((ROOT / 'masterv_schema.sql').read_text())
        with conn:
            conn.executemany('INSERT INTO cities(id,name) VALUES (?,?) '
                             'ON CONFLICT(id) DO UPDATE SET name=excluded.name', CITIES.items())
            columns = [*FIELD_MAP, 'source_date', 'raw_json', 'collected_at', 'imported_at']
            update = ', '.join(f'{c}=excluded.{c}' for c in columns if c != 'data_id')
            conn.executemany(
                f"INSERT INTO projects ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
                f'ON CONFLICT(data_id) DO UPDATE SET {update} '
                'WHERE excluded.collected_at >= projects.collected_at', records)
    return len(records)


def save_details(data_id, payload, db_path=DB_PATH):
    """Replace a project's complete detail snapshot in one transaction.

    Unmapped codes and values remain unchanged; full API response retains
    materials, layouts, developer profile, documents and other attributes.
    """
    if not isinstance(payload, dict) or payload.get('error') is not False or payload.get('code') != 200:
        raise ValueError('Unsuccessful details response.')
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('results'), list):
        raise ValueError('Missing detail results.')
    timestamp = datetime.now(timezone.utc).isoformat()
    dump = lambda value: json.dumps(value, ensure_ascii=False)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        with conn:
            conn.execute('DELETE FROM project_details WHERE data_id=?', (data_id,))
            conn.execute('INSERT INTO project_details VALUES (?,?,?)', (data_id,dump(payload),timestamp))
            for phase in data['results']:
                phase_id = phase['DataPhasId']
                conn.execute('INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (data_id,phase_id,phase.get('DataPhas'),phase.get('DataStatus'),
                     phase.get('DataPhasDeliveryFrom'),phase.get('DataPhasDeliveryTo'),
                     phase.get('DataPhasClubFees'),phase.get('DataPhasCashDiscount'),
                     phase.get('DataPhasMaintenance'),phase.get('DataPhasParkingFees'),dump(phase)))
                finishing = phase.get('DataFinishing') or {}
                for kind, units in (phase.get('DataDetails') or {}).items():
                    for unit in units:
                        conn.execute('INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                            (data_id,phase_id,unit['DetailId'],kind,unit.get('DetailBedRooms'),
                             unit.get('DetailBuiltUpArea'),unit.get('DetailUnitTotalPrice'),
                             unit.get('DetailUnitTotalPriceTo'),unit.get('DetailUnitTotalCashFrom'),
                             unit.get('DetailUnitTotalCashTo'),finishing.get(kind),dump(unit)))
                for plan in phase.get('DataPayPlans') or []:
                    conn.execute('INSERT INTO payment_plans VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (data_id,phase_id,plan['PayPlanId'],plan.get('PayPlanDownPayment'),
                         plan.get('PayPlanInstalment'),plan.get('PayPlanFrequencyInstalment'),
                         plan.get('PayPlanStartInstalment'),plan.get('PayPlanDiscount'),
                         plan.get('PayPlanAllBulks'),plan.get('PayPlanComment'),dump(plan)))
            conn.execute('INSERT OR REPLACE INTO detail_fetch_state VALUES (?,?,?,?)',
                         (data_id,'success',timestamp,None))
