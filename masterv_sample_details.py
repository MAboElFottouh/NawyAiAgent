"""Fetch five random project detail responses directly into SQLite for inspection."""
from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3

import requests
from MasterV import MasterV, MasterVError, DATA_URL
from masterv_database import DB_PATH


def sample_details():
    with closing(sqlite3.connect(DB_PATH)) as db:
        db.row_factory = sqlite3.Row
        projects = db.execute('''SELECT * FROM projects_with_city
            WHERE compound_id IS NOT NULL AND developer_id IS NOT NULL
              AND json_extract(raw_json, '$.DataDeliveryFrom') IS NOT NULL
            ORDER BY RANDOM() LIMIT 5''').fetchall()
        if len(projects) != 5:
            raise MasterVError('Five eligible projects (DataDeliveryFrom is not null) with request identifiers are required.')
        db.execute('''CREATE TABLE IF NOT EXISTS project_detail_samples (
            sample_id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL,
            data_id INTEGER NOT NULL REFERENCES projects(data_id),
            query_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            http_status INTEGER,
            success INTEGER NOT NULL,
            response_json TEXT,
            error TEXT,
            UNIQUE(run_id, data_id)
        )''')
        db.commit()
        client = MasterV()
        run_id = datetime.now(timezone.utc).isoformat()
        failures = 0
        try:
            client.login()
            headers = client.data_headers()
            for project in projects:
                params = {'CompoundId': project['compound_id'], 'SectionId': 1,
                          'DeveloperId': project['developer_id'], 'Currency': 1,
                          'CityId': project['city_id'], 'ViewAll': 'True'}
                payload, status, error, success = None, None, None, False
                try:
                    response = client.session.get(DATA_URL, params=params, headers=headers,
                                                  timeout=(10, 60), allow_redirects=False)
                    status = response.status_code
                    try:
                        payload = response.json()
                    except ValueError:
                        raise MasterVError('Response is not JSON.') from None
                    success = (200 <= status < 300 and isinstance(payload, dict)
                               and payload.get('error') is False and payload.get('code') == 200)
                    if not success:
                        error = f'API did not confirm success (HTTP {status}).'
                except (requests.RequestException, MasterVError) as exc:
                    error = str(exc) if isinstance(exc, MasterVError) else 'Network, TLS or timeout failure.'
                with db:
                    db.execute('''INSERT INTO project_detail_samples
                        (run_id,data_id,query_json,fetched_at,http_status,success,response_json,error)
                        VALUES (?,?,?,?,?,?,?,?)''',
                        (run_id,project['data_id'],json.dumps(params),datetime.now(timezone.utc).isoformat(),
                         status,int(success),json.dumps(payload,ensure_ascii=False) if payload is not None else None,error))
                print(f"{project['name']} | {project['city_name']} | compound={project['compound_id']} | success={success}", flush=True)
                failures += not success
        finally:
            client.close()
        print(f'Run: {run_id}; successful: {5-failures}/5; table: project_detail_samples', flush=True)
        return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(sample_details())
