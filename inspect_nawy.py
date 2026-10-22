"""Collect up to 500 unique Nawy listings with durable resume checkpoints."""

import fcntl
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

import database

SEARCH_URL = "https://www.nawy.com/en/search?category=property"
LIMIT = 500
DATA_DIR = Path(__file__).resolve().parent / "data"
# Keep the existing lock path to coordinate with any older running script.
LOCK_PATH = DATA_DIR / "nawy_properties.lock"


def page_props(html):
    """Read the structured data embedded in the public HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None:
        raise ValueError("Missing __NEXT_DATA__; the page structure may have changed.")
    props = json.loads(script.get_text()).get("props", {}).get("pageProps")
    if not isinstance(props, dict):
        raise ValueError("Missing pageProps in page data.")
    return props


def property_url(result):
    url = urljoin(SEARCH_URL, result["shareLink"])
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "www.nawy.com":
        raise ValueError(f"Unexpected property URL: {url}")
    match = re.search(r"/property/(\d+)(?:-|/|$)", parsed.path)
    if not match or match.group(1) != str(result["id"]):
        raise ValueError(f"Property URL does not match ID {result['id']}")
    return url


def extract_property(html, url, expected_id):
    prop = page_props(html).get("property")
    if not isinstance(prop, dict) or str(prop.get("id")) != str(expected_id):
        raise ValueError(f"Detail page does not contain property {expected_id}.")
    return normalize_property(prop, url)


def unique_items(items):
    """Remove exact duplicates while preserving source order."""
    seen, result = set(), []
    for item in items:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def compact(record):
    # Zero and False are meaningful (e.g. commercial units with zero bedrooms).
    return {k: v for k, v in record.items() if v is not None and v != "" and v != [] and v != {}}


def normalize_property(prop, url):
    """Keep useful listing fields, without the original raw payload."""
    compound = prop.get("compound") or {}
    price = prop.get("price")
    if price is None:
        price = prop.get("minPrice")
    area = prop.get("minUnitArea")
    result = {
        "id": prop["id"],
        "url": url,
        "name": prop.get("name"),
        "property_type": (prop.get("propertyType") or {}).get("name"),
        "compound": compound.get("name"),
        "developer": prop.get("developerName"),
        "location": prop.get("areaName"),
        "parent_location": prop.get("parentAreaName"),
        "price": price,
        "area_m2": area,
        "bedrooms": prop.get("numberOfBedrooms"),
        "bathrooms": prop.get("numberOfBathrooms"),
        "finishing": prop.get("finishing"),
        "delivery_date": (prop.get("deliveryDate") or "").split("T")[0],
        "resale": prop.get("resale"),
        "on_sale": prop.get("onSale"),
        "description": "\n".join(unique_items(BeautifulSoup(
            prop.get("description") or "", "html.parser"
        ).get_text("\n", strip=True).splitlines())),
        "amenities": unique_items([
            item["name"].strip() for item in (prop.get("amenities") or [])
            if item.get("name") and item["name"].strip()
        ]),
        "image_url": next(iter(prop.get("images") or []), None),
    }
    if result["parent_location"] == result["location"]:
        result.pop("parent_location")
    # Only store additional bounds when they carry different information.
    for key, value, base in [
        ("min_price", prop.get("minPrice"), price),
        ("max_price", prop.get("maxPrice"), price),
        ("max_area_m2", prop.get("maxUnitArea"), area),
    ]:
        if value is not None and value != base:
            result[key] = value

    plans = []
    for plan in prop.get("paymentPlans") or []:
        cleaned = compact({
            "currency": plan.get("currency"),
            "is_cash": plan.get("isCash"),
            "frequency": plan.get("frequency"),
            "years": plan.get("years"),
            "years_remaining": plan.get("yearsRemaining"),
            "installment_amount": plan.get("singleInstallmentAmount"),
            "installment_type": plan.get("installmentType"),
            "down_payment": plan.get("downPayment"),
            "offer_valid_until": plan.get("offerValidTill"),
            "bulk_payments": unique_items(plan.get("bulkPayments") or []),
            "extra_fees": unique_items([
                compact({k: v for k, v in fee.items() if k != "frequencyType" or v != fee.get("frequency")})
                for fee in (plan.get("milestones") or [])
            ]),
        })
        if cleaned.get("years_remaining") == cleaned.get("years"):
            cleaned.pop("years_remaining", None)
        if plan.get("unitPrice") is not None and plan["unitPrice"] != price:
            cleaned["price"] = plan["unitPrice"]
        for source, target in {
            "downPaymentMonth1": "payment_after_1_month",
            "downPaymentMonth3": "payment_after_3_months",
            "downPaymentMonth6": "payment_after_6_months",
            "deliveryPayment": "delivery_payment",
            "contractualPayment": "contractual_payment",
        }.items():
            if plan.get(source):
                cleaned[target] = plan[source]
        plans.append(cleaned)
    result["payment_plans"] = unique_items(plans)
    return compact(result)


def save_state(state, property_record=None):
    database.save_checkpoint(state, property_record)


def load_state():
    database.init_db()
    state = database.load_checkpoint(ids_only=True)
    state.update(source_url=SEARCH_URL, requested_count=LIMIT)
    state.setdefault("next_page", 1)
    return state


class Fetcher:
    def __init__(self, session):
        self.session = session
        self.last_request = None

    def get(self, url):
        if self.last_request is not None:
            time.sleep(random.uniform(3, 5))
        try:
            response = self.session.get(url, timeout=(10, 30))
            response.raise_for_status()
            return response.text
        finally:
            self.last_request = time.monotonic()


def retry_after_seconds(value):
    try:
        return max(60, int(value))
    except (ValueError, TypeError):
        try:
            return max(60, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 60


def collect(state, fetcher):
    saved_ids = {str(prop["id"]) for prop in state["properties"]}
    print(f"Saved: {len(saved_ids)} | Total target: {LIMIT}", flush=True)
    if len(saved_ids) >= LIMIT:
        print("The target has been reached. No new requests are needed.", flush=True)
        return 0
    remaining = state.get("retry_not_before", 0) - time.time()
    if remaining > 0:
        print(f"The site requested a cooldown. Run the script again in {int(remaining) + 1} seconds.")
        return 1
    page = state["next_page"]
    previous_ids = None
    while len(saved_ids) < LIMIT:
        url = f"{SEARCH_URL}&page_number={page}"
        data = page_props(fetcher.get(url)).get("loadedSearchResultsSSR")
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ValueError("Search results structure changed; stopping without losing progress.")
        if data.get("page") != page:
            raise ValueError("The site returned a different page; stopping to avoid repeated requests.")
        total = data.get("total")
        state["total_available"] = total
        print(f"Total listings in search results: {total} | Page: {page}", flush=True)
        results = data["results"]
        ids = tuple(str(item["id"]) for item in results)
        if ids and ids == previous_ids:
            raise ValueError("Repeated search page; stopping.")
        previous_ids = ids
        if not results:
            print("No more search results are available.", flush=True)
            save_state(state)
            return 1
        # Refresh IDs before detail requests, including units saved by other tools.
        saved_ids.update(database.get_property_ids())
        state["properties"] = [{"id": int(pid)} for pid in saved_ids]
        for result in results:
            if len(saved_ids) >= LIMIT:
                break
            if str(result["id"]) in saved_ids:
                print(f"Skipping {result['id']}: already in SQLite (no detail request).", flush=True)
                continue
            url = property_url(result)
            print(f"[{len(saved_ids) + 1}/{LIMIT}] Fetching {result['id']}...", flush=True)
            prop = extract_property(fetcher.get(url), url, result["id"])
            state["properties"].append({"id": prop["id"]})
            saved_ids.add(str(prop["id"]))
            state.pop("last_error", None)
            state.pop("retry_not_before", None)
            state.pop("errors", None)
            # Stay on this page until every result is processed; saved IDs are skipped.
            save_state(state, prop)
        if len(saved_ids) >= LIMIT:
            print(f"Saved {len(saved_ids)} unique properties to {database.DB_PATH}", flush=True)
            return 0
        page += 1
        state["next_page"] = page
        save_state(state)
    return 0


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Prevent two local runs from overwriting each other's progress.
    with LOCK_PATH.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another instance of the scraper is already running.", file=sys.stderr)
            return 1
        try:
            state = load_state()
            save_state(state)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Cannot load checkpoint; existing data was not replaced: {exc}", file=sys.stderr)
            return 1
        try:
            with requests.Session() as session:
                session.headers.update({"User-Agent": "NawyPropertyInspector/0.1", "Accept-Language": "en"})
                return collect(state, Fetcher(session))
        except KeyboardInterrupt:
            print("\nStopped. The next run will resume from the saved progress.", flush=True)
            return 130
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            state["last_error"] = str(exc)
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 429:
                delay = retry_after_seconds(response.headers.get("Retry-After"))
                state["retry_not_before"] = time.time() + delay
                print(f"429: Scraping stopped. Wait at least {int(delay)} seconds.", flush=True)
            elif response is not None and response.status_code == 403:
                print("403: The site denied the request. Scraping stopped. Review the cause before restarting.", flush=True)
            save_state(state)
            print(f"Stopped: {exc}. Saved: {len(state['properties'])}/{LIMIT}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
