"""Read-only, parameterized property search; usable by a future LangChain tool."""
import json
import math
from datetime import date
import sqlite3
from contextlib import closing, nullcontext

import database

TYPE_ALIASES = {'شقة': 'Apartment', 'شقه': 'Apartment', 'فيلا': 'Villa',
                'ڤيلا': 'Villa', 'تاون هاوس': 'Townhouse', 'توين هاوس': 'Twinhouse',
                'شاليه': 'Chalet', 'استوديو': 'Studio', 'مكتب': 'Office'}
LOCATION_ALIASES = {'NewCairo': 'New Cairo', 'newcairo': 'New Cairo', 'القاهرة الجديدة': 'New Cairo', 'القاهره الجديده': 'New Cairo',
                    'الشيخ زايد': 'El Sheikh Zayed', 'زايد الجديدة': 'New Zayed',
                    'العاصمة الإدارية': 'New Capital City', 'العاصمه الاداريه': 'New Capital City',
                    'العين السخنة': 'Ain Sokhna', 'العين السخنه': 'Ain Sokhna',
                    '٦ أكتوبر': '6th of October City', '6 أكتوبر': '6th of October City',
                    '6 اكتوبر': '6th of October City', 'الساحل الشمالي': 'North Coast-Sahel'}


def _number(value, name, integer=False):
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                              or not math.isfinite(value) or value < 0
                              or (integer and int(value) != value)):
        raise ValueError(f'{name} must be a non-negative {"integer" if integer else "number"}.')


def _text(value, aliases=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Text filters must be non-empty strings.')
    value = value.strip()
    return (aliases or {}).get(value, value)


def _like(value):
    return '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def search_properties(*, property_type=None, location=None, compound=None,
                      min_price=None, max_price=None, min_area_m2=None, max_area_m2=None,
                      target_price=None, target_area_m2=None,
                      price_tolerance=0.10,
                      bedrooms=None, bathrooms=None, payment_method=None,
                      max_down_payment=None, finishing=None, delivery_by=None, limit=5, _connection=None, _limit_cap=None):
    """Search stored listings without an LLM or network access.

    Prices/down payments are EGP. Bedrooms, bathrooms and target area are minima.
    target_price allows prices up to 110% of the budget, with no implicit floor.
    Explicit min/max bounds remain strict. Rank by summed relative distance to
    requested price/area (midpoints for advertised ranges), then price and ID.
    Area and price constraints use conservative bounds: the entire advertised
    range must satisfy the filter. No relaxed matches are returned silently.
    Payment criteria must match the SAME payment plan. Missing values do not
    satisfy a filter. Returned total counts all matching stored listings.
    """
    for name, value in {'min_price': min_price, 'max_price': max_price,
                        'min_area_m2': min_area_m2, 'max_area_m2': max_area_m2,
                        'max_down_payment': max_down_payment}.items():
        _number(value, name)
    for name, value in {'bedrooms': bedrooms, 'bathrooms': bathrooms, 'limit': limit}.items():
        _number(value, name, integer=True)
    if limit is None or limit < 1:
        raise ValueError('limit must be a positive integer.')
    if delivery_by is not None:
        if not isinstance(delivery_by, str):
            raise ValueError('delivery_by must be an ISO date (YYYY-MM-DD).')
        date.fromisoformat(delivery_by)
    for low, high in [(min_price, max_price), (min_area_m2, max_area_m2)]:
        if low is not None and high is not None and low > high:
            raise ValueError('Minimum cannot exceed maximum.')
    if payment_method not in (None, 'cash', 'installments'):
        raise ValueError('payment_method must be cash or installments.')

    for name, target in [('target_price', target_price), ('target_area_m2', target_area_m2)]:
        _number(target, name)
        if target is not None and target == 0:
            raise ValueError(f'{name} must be positive.')
    _number(price_tolerance, 'price_tolerance')
    if price_tolerance is None or price_tolerance > 1:
        raise ValueError('price_tolerance must be between 0 and 1.')
    if target_price is not None:
        upper = round(target_price * (1 + price_tolerance), 2)
        max_price = upper if max_price is None else min(max_price, upper)
    if target_area_m2 is not None:
        min_area_m2 = target_area_m2 if min_area_m2 is None else max(min_area_m2, target_area_m2)
    applied_filters = dict(min_price=min_price, max_price=max_price,
                           min_area_m2=min_area_m2, max_area_m2=max_area_m2,
                           min_bedrooms=bedrooms, min_bathrooms=bathrooms)
    # Conflicting minimum requirements and hard limits yield no results.
    clauses, params = ['(p.on_sale = 1 OR p.on_sale IS NULL)'], []
    if property_type is not None:
        clauses.append('p.property_type = ? COLLATE NOCASE')
        params.append(_text(property_type, TYPE_ALIASES))
    if location is not None:
        clauses.append("(p.location LIKE ? ESCAPE '\\' OR p.parent_location LIKE ? ESCAPE '\\')")
        params.extend([_like(_text(location, LOCATION_ALIASES))] * 2)
    if compound is not None:
        clauses.append("p.compound LIKE ? ESCAPE '\\'")
        params.append(_like(_text(compound)))
    if finishing is not None:
        clauses.append('p.finishing = ? COLLATE NOCASE')
        params.append(_text(finishing))
    if delivery_by is not None:
        clauses.append('date(p.delivery_date) <= date(?)')
        params.append(delivery_by)
    for expression, operator, value in [
        ('COALESCE(p.min_price, p.price)', '>=', min_price),
        ('COALESCE(p.max_price, p.price)', '<=', max_price),
        ('p.area_m2', '>=', min_area_m2),
        ('COALESCE(p.max_area_m2, p.area_m2)', '<=', max_area_m2),
        ('p.bedrooms', '>=', bedrooms), ('p.bathrooms', '>=', bathrooms),
    ]:
        if value is not None:
            clauses.append(f'{expression} {operator} ?')
            params.append(value)
    if any(v is not None for v in (min_price, max_price, payment_method, max_down_payment)):
        plan_clauses = ["json_extract(plan.value, '$.currency') = 'EGP'"]
        if payment_method is not None:
            plan_clauses.append("json_extract(plan.value, '$.is_cash') = ?")
            params.append(int(payment_method == 'cash'))
        if max_down_payment is not None:
            # A cash plan's zero deposit is not a zero-cost purchase.
            plan_clauses.append("CASE WHEN json_extract(plan.value, '$.is_cash') = 1 "
                                "THEN COALESCE(json_extract(plan.value, '$.price'), p.price) "
                                "ELSE json_extract(plan.value, '$.down_payment') END <= ?")
            params.append(max_down_payment)
        clauses.append('EXISTS (SELECT 1 FROM json_each(p.payment_plans) AS plan WHERE '
                       + ' AND '.join(plan_clauses) + ')')
    where = ' AND '.join(clauses)
    distances, rank_params = [], []
    for target, midpoint in [
        (target_price, '(COALESCE(p.min_price, p.price) / 2.0 + COALESCE(p.max_price, p.price) / 2.0)'),
        (target_area_m2, '(p.area_m2 / 2.0 + COALESCE(p.max_area_m2, p.area_m2) / 2.0)'),
    ]:
        if target is not None:
            distances.append(f'ABS({midpoint} - ?) / ?')
            rank_params.extend([target, target])
    order = (' + '.join(distances) + ', ') if distances else ''
    order += 'p.price IS NULL, p.price, p.id'
    # mode=ro prevents accidentally creating an empty database on deployment.
    with (nullcontext(_connection) if _connection is not None else
          closing(sqlite3.connect(database.DB_PATH.resolve().as_uri() + '?mode=ro', uri=True))) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute(f'SELECT COUNT(*) FROM properties p WHERE {where}', params).fetchone()[0]
        rows = conn.execute(f'SELECT p.* FROM properties p WHERE {where} '
                            f'ORDER BY {order} LIMIT ?', params + rank_params + [int(limit)]).fetchall()
    properties = []
    for row in rows:
        prop = {k: row[k] for k in row.keys() if row[k] is not None}
        for key in database.JSON_FIELDS:
            if key in prop:
                prop[key] = json.loads(prop[key])
        for key in database.BOOL_FIELDS:
            if key in prop:
                prop[key] = bool(prop[key])
        properties.append(prop)
    return {'source': 'sqlite', 'total_matches': total, 'applied_filters': applied_filters,
            'properties': properties}


def nearby_properties(_exact_result=None, **filters):
    """Rank non-matching alternatives without mutating the original filters."""
    exact = _exact_result if _exact_result is not None else search_properties(**filters)
    if exact['total_matches']:
        return {**exact, 'match_type': 'exact'}
    count = search_properties(limit=1)['total_matches']
    pool = search_properties(limit=max(count, 1))['properties']
    groups = {
        'property_type': ('property_type',), 'location': ('location',), 'compound': ('compound',),
        'price': ('target_price', 'min_price', 'max_price'),
        'area_m2': ('target_area_m2', 'min_area_m2', 'max_area_m2'),
        'bedrooms': ('bedrooms',), 'bathrooms': ('bathrooms',),
        'payment_plan': ('payment_method', 'max_down_payment'),
        'finishing': ('finishing',), 'delivery_date': ('delivery_by',),
    }
    criteria = []
    for label, keys in groups.items():
        selected = {k: filters[k] for k in keys if filters.get(k) is not None}
        if not selected:
            continue
        query = dict(selected)
        if label == 'price':
            query['price_tolerance'] = filters.get('price_tolerance', .1)
        matches = search_properties(**query, limit=max(count, 1))['properties']
        criteria.append((label, selected, {p['id'] for p in matches}))
    ranked = []
    for prop in pool:
        differences, distance = [], 0.0
        for label, requested, matched_ids in criteria:
            if prop['id'] in matched_ids:
                continue
            if label == 'payment_plan':
                actual = prop.get('payment_plans')
            elif label == 'location':
                actual = {'location': prop.get('location'), 'parent_location': prop.get('parent_location')}
            elif label == 'price':
                actual = {'price': prop.get('price'), 'min_price': prop.get('min_price'), 'max_price': prop.get('max_price')}
            elif label == 'area_m2':
                actual = {'area_m2': prop.get('area_m2'), 'max_area_m2': prop.get('max_area_m2')}
            else:
                actual = prop.get(label)
            differences.append({'field': label, 'requested': requested, 'actual': actual,
                                'reason': 'Does not satisfy the requested condition or cannot be verified.'})
        for key, value in [('price', filters.get('target_price') or filters.get('max_price')),
                           ('area_m2', filters.get('target_area_m2') or filters.get('min_area_m2')),
                           ('bedrooms', filters.get('bedrooms')), ('bathrooms', filters.get('bathrooms'))]:
            if value:
                distance += abs(prop[key] - value) / value if prop.get(key) is not None else 10
        ranked.append((len(differences), distance, prop['id'], {**prop, 'differences': differences}))
    ranked.sort(key=lambda row: row[:3])
    return {'source': 'sqlite', 'match_type': 'alternative', 'total_matches': 0,
            'applied_filters': exact.get('applied_filters', {}),
            'requested_filters': filters, 'available_alternatives': len(ranked),
            'properties': [row[3] for row in ranked[:filters.get('limit', 5)]],
            'note': 'Non-matching alternatives only. Original requirements have NOT changed.'}
