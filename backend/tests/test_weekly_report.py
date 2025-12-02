import json
from datetime import date

import pytest

import backend.app as appmod


class DummyCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *args, **kwargs):
        return None

    def fetchall(self):
        return self._rows


class DummyConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return DummyCursor(self._rows)

    def close(self):
        pass


def test_weekly_report_basic(monkeypatch):
    # Simulate three venues:
    # A: has an unvalidated event (unposted)
    # B: no event
    # C: posted
    # For each venue we return (id, name, events_json)
    rows = [
        (1, 'Venue A', [
            {'id': 101, 'event_date': date(2025, 12, 1), 'status': 'unposted', 'is_validated': False}
        ]),
        (2, 'Venue B', []),
        (3, 'Venue C', [
            {'id': 102, 'event_date': date(2025, 12, 3), 'status': 'posted', 'is_validated': True}
        ]),
    ]

    monkeypatch.setattr(appmod, 'getconn', lambda: DummyConn(rows))

    client = appmod.app.test_client()
    res = client.get('/admin/weekly-report?week_ending=2025-12-07')
    assert res.status_code == 200
    j = json.loads(res.data)
    assert j['week_start'] == '2025-12-01'
    assert j['week_end'] == '2025-12-07'
    assert len(j['rows']) == 3

    by_venue = {r['venue']: r for r in j['rows']}
    assert by_venue['Venue A']['state'] == 'unvalidated'
    assert by_venue['Venue B']['state'] == 'no_submission'
    assert by_venue['Venue C']['state'] == 'posted'
    # Validate events array structure
    assert isinstance(by_venue['Venue A']['events'], list) and len(by_venue['Venue A']['events']) == 1
    assert by_venue['Venue C']['events'][0]['status'] == 'posted'


def test_weekly_report_multiple_events_same_venue(monkeypatch):
    # Venue D has two events within the week (one unvalidated, one posted)
    rows = [
        (4, 'Venue D', [
            {'id': 201, 'event_date': date(2025, 12, 2), 'status': 'unposted', 'is_validated': False},
            {'id': 202, 'event_date': date(2025, 12, 6), 'status': 'posted', 'is_validated': True},
        ])
    ]

    monkeypatch.setattr(appmod, 'getconn', lambda: DummyConn(rows))
    client = appmod.app.test_client()
    res = client.get('/admin/weekly-report?week_ending=2025-12-07')
    assert res.status_code == 200
    j = json.loads(res.data)
    assert len(j['rows']) == 1
    v = j['rows'][0]
    assert v['venue'] == 'Venue D'
    assert v['state'] == 'posted'  # because at least one event was posted
    assert len(v['events']) == 2
