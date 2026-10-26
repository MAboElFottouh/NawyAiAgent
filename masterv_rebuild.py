"""Build a fresh MasterV database, verify it, then replace the active snapshot.

Run: python masterv_rebuild.py
Resume failed detail requests: python masterv_rebuild.py --resume
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from MasterV import MasterV
from masterv_database import DB_PATH


def rebuild(resume=False):
    staging = DB_PATH.with_name('masterv_rebuild.db')
    if staging.exists() and not resume:
        raise RuntimeError('Rebuild database exists; use --resume to continue it.')
    if resume and not staging.exists():
        raise RuntimeError('No rebuild database to resume.')
    client = MasterV()
    try:
        client.login()
        if not resume:
            client.fetch_cities(staging)
        else:
            with closing(sqlite3.connect(staging)) as db:
                cities = db.execute('SELECT count(DISTINCT city_id) FROM projects').fetchone()[0]
            if cities != 7:
                client.fetch_cities(staging)
        client.fetch_details(staging, resume=resume)
    finally:
        client.close()
    with closing(sqlite3.connect(staging)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        missing = db.execute("""SELECT count(*) FROM projects p WHERE
            json_extract(raw_json,'$.DataDeliveryFrom') IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM project_details d WHERE d.data_id=p.data_id)""").fetchone()[0]
        assert missing == 0, f'Missing details: {missing}'
        for table in ('cities','projects','project_details','phases','units','payment_plans'):
            print(f'{table}: {db.execute("SELECT count(*) FROM " + table).fetchone()[0]}')
    if DB_PATH.exists():
        folder = DB_PATH.parent / 'backups'
        folder.mkdir(exist_ok=True)
        backup = folder / ('masterv_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '.db')
        with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(backup)) as dest:
            src.backup(dest)
        print(f'Backup: {backup}')
    staging.replace(DB_PATH)
    print(f'Fresh database ready: {DB_PATH}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', action='store_true')
    rebuild(parser.parse_args().resume)
