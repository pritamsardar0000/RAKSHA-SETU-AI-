"""Zero-dependency development API for the RakshaSetu SIH dashboard.

Run with: ``py backend/api.py``
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from threading import Lock
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from decision_engine import SUPPORTED_HAZARDS, case_studies, case_study_detail, hazard_scenarios, main, recent_disasters, recommend_shelter

SEARCH_CACHE = Path(__file__).resolve().parents[1] / "data" / "location_cache.json"
AUTHORITY_DATA = Path(__file__).resolve().parents[1] / "data" / "prototype_authority_data.json"
GEOCODE_LOCK = Lock()
AUTHORITY_LOCK = Lock()
LAST_GEOCODE_AT = 0.0
NOMINATIM_MIN_INTERVAL_SECONDS = 1.0
ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
SEARCH_COUNTRIES = "in,np,id"
VERIFIED_RISKS = {"High", "Moderate", "Low"}
INDIAN_PINCODE = re.compile(r"^[1-9]\d{5}$")
PINCODE_HINTS = {
    "700100": {"address": "Nabinpur, South 24 Parganas, West Bengal, India", "latitude": 22.3774, "longitude": 88.6086},
    "700034": {"address": "Behala, Kolkata, West Bengal, India", "latitude": 22.4870, "longitude": 88.3120},
    "700001": {"address": "Kolkata GPO, Kolkata, West Bengal, India", "latitude": 22.5726, "longitude": 88.3639},
    "700091": {"address": "New Town, Kolkata, West Bengal, India", "latitude": 22.5958, "longitude": 88.4797},
    "743512": {"address": "Samali, South 24 Parganas, West Bengal, India", "latitude": 22.4010, "longitude": 88.4450},
}


def _load_search_cache() -> dict:
    try:
        data = json.loads(SEARCH_CACHE.read_text(encoding="utf-8"))
        return data if isinstance(data.get("items"), dict) else {"items": {}}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"items": {}}


def _load_authority_data() -> dict:
    """Load the local-only authority demo store without exposing passwords to the UI."""
    default = {"schema_version": "1.0", "users": [], "reports": [], "risk_overrides": {}}
    try:
        data = json.loads(AUTHORITY_DATA.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default
        data.setdefault("users", [])
        data.setdefault("reports", [])
        data.setdefault("risk_overrides", {})
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_authority_data(data: dict) -> None:
    AUTHORITY_DATA.parent.mkdir(parents=True, exist_ok=True)
    temporary = AUTHORITY_DATA.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(AUTHORITY_DATA)


def _public_user(user: dict) -> dict:
    return {key: user.get(key) for key in ("username", "role", "name", "title")}


def authority_summary() -> dict:
    with AUTHORITY_LOCK:
        data = _load_authority_data()
    reports = data["reports"]
    incident_counts = dict(Counter(str(item.get("incident_type") or "Other") for item in reports))
    return {
        "users": [_public_user(user) for user in data["users"]],
        "reports": reports,
        "summary": {
            "total_reports": len(reports),
            "awaiting_verification": sum(item.get("status") in {"Awaiting field verification", "Auto-high risk — awaiting officer validation"} for item in reports),
            "verified_reports": sum(item.get("status") == "Field verified" for item in reports),
            "closed_reports": sum(item.get("status") in {"Cancelled", "Rejected as fake"} for item in reports),
            "active_risk_overrides": len(data["risk_overrides"]),
            "auto_high_reports": sum(1 for item in reports if item.get("auto_high") and item.get("status") not in {"Cancelled", "Rejected as fake"}),
            "incident_counts": incident_counts,
        },
    }


def _linked_area(report: dict) -> dict | None:
    hazard = report.get("hazard", "flood")
    if hazard not in SUPPORTED_HAZARDS:
        hazard = "flood"
    zones = main(hazard).get("zones", [])
    location_id = report.get("location_id")
    if location_id:
        match = next((zone for zone in zones if zone["id"] == location_id), None)
        if match:
            return match
    location = str(report.get("location", "")).strip().casefold()
    exact = next((zone for zone in zones if zone["name"].casefold() == location), None)
    if exact:
        return exact
    try:
        latitude, longitude = float(report["latitude"]), float(report["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    def distance(zone: dict) -> float:
        lat1, lon1 = math.radians(latitude), math.radians(longitude)
        lat2, lon2 = math.radians(zone["latitude"]), math.radians(zone["longitude"])
        h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        return 2 * 6371 * math.asin(math.sqrt(h))
    nearest = min(zones, key=distance, default=None)
    return nearest if nearest and distance(nearest) <= 15 else None


def create_report(payload: dict) -> dict:
    required = {key: str(payload.get(key, "")).strip() for key in ("incident_type", "location", "description")}
    if not all(required.values()):
        raise ValueError("incident_type, location, and description are required.")
    pincode = str(payload.get("pincode", "")).strip()
    if not INDIAN_PINCODE.fullmatch(pincode):
        raise ValueError("Enter a valid six-digit Indian area PIN code before submitting the report.")
    try:
        community_rating = max(1, min(5, int(payload.get("community_rating", 3) or 3)))
    except (TypeError, ValueError) as error:
        raise ValueError("community_rating must be a number from 1 to 5.") from error
    hazard = str(payload.get("hazard", "flood")).lower()
    if hazard not in SUPPORTED_HAZARDS:
        hazard = "flood"
    try:
        latitude = float(payload.get("latitude"))
        longitude = float(payload.get("longitude"))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Choose the incident location from the map or use current GPS before submitting.")
    raw_accuracy = payload.get("accuracy")
    try:
        accuracy = float(raw_accuracy) if raw_accuracy not in (None, "", "None") else None
    except (TypeError, ValueError):
        accuracy = None
    source_role = "field_officer" if payload.get("source_role") == "field_officer" else "community"
    location_id = str(payload.get("location_id", "")).strip() or None
    report = {
        "id": f"report-{int(time.time() * 1000)}",
        **required,
        "hazard": hazard,
        "location_id": location_id,
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": accuracy,
        "address": str(payload.get("address", "")).strip() or required["location"],
        "pincode": pincode,
        "severity": str(payload.get("severity", "Moderate")).title(),
        "community_rating": community_rating,
        "reporter": "Field Officer" if source_role == "field_officer" else "Local Community User",
        "status": "Awaiting field verification",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verification": None,
        "field_observation": str(payload.get("field_observation", "")).strip() or None,
        "final_risk": None,
        "auto_high": False,
        "backend_action": None,
    }
    with AUTHORITY_LOCK:
        data = _load_authority_data()
        linked_area = _linked_area(report)
        if linked_area:
            report["location_id"] = linked_area["id"]
        def near_existing(item: dict) -> bool:
            if linked_area and item.get("location_id") == linked_area["id"]:
                return True
            try:
                lat1, lon1 = latitude, longitude
                lat2, lon2 = float(item["latitude"]), float(item["longitude"])
                lat1, lat2 = math.radians(lat1), math.radians(lat2)
                dlat, dlon = lat2 - lat1, math.radians(lon2 - longitude)
                h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                return 2 * 6371 * math.asin(math.sqrt(h)) <= 3
            except (KeyError, TypeError, ValueError):
                return False
        nearby_count = 1 + sum(1 for item in data["reports"] if item.get("hazard") == hazard and item.get("status") not in {"Cancelled", "Rejected as fake"} and near_existing(item))
        auto_high = source_role == "community" and (community_rating >= 4 or nearby_count >= 4)
        if auto_high:
            report.update({
                "status": "Auto-high risk — awaiting officer validation",
                "severity": "High",
                "final_risk": "High",
                "auto_high": True,
                "community_report_count": nearby_count,
                "backend_action": {
                    "type": "community_auto_high_risk",
                    "result": f"Community report promoted to High risk immediately ({nearby_count} corroborating report(s) / rating {community_rating}/5). Field officer validation remains available.",
                },
            })
            if linked_area:
                data["risk_overrides"][linked_area["id"]] = {
                    "report_id": report["id"],
                    "hazard": hazard,
                    "final_risk": "High",
                    "auto_high": True,
                    "verified_by": None,
                    "verified_at": None,
                }
        data["reports"] = [report, *data["reports"]][:100]
        _save_authority_data(data)
    return report


def verify_report(report_id: str, payload: dict) -> dict:
    username = str(payload.get("username", "")).strip()
    final_risk = str(payload.get("final_risk", "")).title()
    verification = str(payload.get("verification", "")).strip()
    if final_risk not in VERIFIED_RISKS or not verification:
        raise ValueError("final_risk (High, Moderate, or Low) and verification are required.")
    with AUTHORITY_LOCK:
        data = _load_authority_data()
        officer = next((user for user in data["users"] if user.get("username") == username), None)
        if not officer or officer.get("role") not in {"field_officer", "admin"}:
            raise PermissionError("A field officer or admin login is required to verify a report.")
        report = next((item for item in data["reports"] if item.get("id") == report_id), None)
        if report is None:
            raise LookupError("Report was not found.")
        verified_at = datetime.now(timezone.utc).isoformat()
        report.update({
            "status": "Field verified",
            "verification": verification,
            "final_risk": final_risk,
            "auto_high": False,
            "verified_by": officer.get("name"),
            "verified_at": verified_at,
        })
        area = _linked_area(report)
        if area:
            data["risk_overrides"][area["id"]] = {
                "report_id": report_id,
                "hazard": report["hazard"],
                "final_risk": final_risk,
                "auto_high": False,
                "verified_by": officer.get("name"),
                "verified_at": verified_at,
            }
            report["backend_action"] = {
                "type": "verified_risk_override",
                "area_id": area["id"],
                "area_name": area["name"],
                "result": f"{area['name']} will be marked {final_risk} on the {report['hazard']} dashboard after refresh.",
            }
        else:
            report["backend_action"] = {
                "type": "manual_map_link_required",
                "result": "Report verified and retained. The typed location is not linked to a mapped hazard zone.",
            }
        _save_authority_data(data)
    return report


def review_report(report_id: str, payload: dict) -> dict:
    """Cancel or reject a report and remove its active risk override, if any."""
    username = str(payload.get("username", "")).strip()
    decision = str(payload.get("decision", "")).strip().lower()
    note = str(payload.get("note", "")).strip()
    if decision not in {"cancel", "fake"}:
        raise ValueError("decision must be cancel or fake.")
    if not note:
        raise ValueError("Add a review note before closing the report.")
    with AUTHORITY_LOCK:
        data = _load_authority_data()
        officer = next((user for user in data["users"] if user.get("username") == username), None)
        if not officer or officer.get("role") not in {"field_officer", "admin"}:
            raise PermissionError("A field officer or admin login is required to review a report.")
        report = next((item for item in data["reports"] if item.get("id") == report_id), None)
        if report is None:
            raise LookupError("Report was not found.")
        for area_id, override in list(data["risk_overrides"].items()):
            if override.get("report_id") == report_id:
                del data["risk_overrides"][area_id]
        reviewed_at = datetime.now(timezone.utc).isoformat()
        report.update({
            "status": "Cancelled" if decision == "cancel" else "Rejected as fake",
            "review_decision": decision,
            "review_note": note,
            "reviewed_by": officer.get("name"),
            "reviewed_at": reviewed_at,
            "final_risk": None,
            "backend_action": {
                "type": "report_closed",
                "result": "Report cancelled by reviewer." if decision == "cancel" else "Report rejected as fake by reviewer.",
            },
        })
        _save_authority_data(data)
    return report


def search_places(query: str) -> dict:
    """Geocode map searches via Nominatim; this endpoint never assigns risk."""
    global LAST_GEOCODE_AT
    normalized = " ".join(query.split())
    if len(normalized) < 2:
        return {"results": [], "error": "Enter at least two characters to search for a location."}

    cache = _load_search_cache()
    # Version the cache key so results saved under the earlier India-only scope are not reused.
    cache_key = f"{SEARCH_COUNTRIES}:{normalized.casefold()}"
    if cache_key in cache["items"]:
        return {"results": cache["items"][cache_key], "error": None, "cached": True}

    request = Request(
        "https://nominatim.openstreetmap.org/search?" + urlencode(
            {"q": normalized, "format": "jsonv2", "limit": 8, "addressdetails": 1, "countrycodes": SEARCH_COUNTRIES}
        ),
        headers={"User-Agent": "DISASTER_MGM-SIH/1.0 (location search; contact: local)"},
    )
    try:
        with GEOCODE_LOCK:
            wait_seconds = NOMINATIM_MIN_INTERVAL_SECONDS - (time.monotonic() - LAST_GEOCODE_AT)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            with urlopen(request, timeout=10) as response:
                raw = json.loads(response.read().decode("utf-8"))
            LAST_GEOCODE_AT = time.monotonic()
    except HTTPError as error:
        return {"results": [], "error": "Location search is temporarily unavailable. Please try again shortly.", "status": error.code}
    except (URLError, TimeoutError, OSError):
        return {"results": [], "error": "Could not reach the location search service. Check your internet connection and try again."}

    results, seen = [], set()
    for item in raw:
        try:
            latitude, longitude = float(item["lat"]), float(item["lon"])
            identifier = f"osm-{item['osm_type']}-{item['osm_id']}"
        except (KeyError, TypeError, ValueError):
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        results.append({
            "id": identifier,
            "name": item.get("display_name", "Unnamed location"),
            "latitude": latitude,
            "longitude": longitude,
            "source": "OpenStreetMap Nominatim",
            "assessment_status": "MAP LOOKUP ONLY — no local AI risk assessment",
        })

    cache["items"][cache_key] = results
    SEARCH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SEARCH_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return {"results": results, "error": None, "cached": False}


def resolve_pincode(pin: str) -> dict:
    """Resolve an Indian PIN to a readable address and optional map point."""
    normalized = str(pin or "").strip()
    if not INDIAN_PINCODE.fullmatch(normalized):
        raise ValueError("Enter a valid six-digit Indian area PIN code.")
    fallback = PINCODE_HINTS.get(normalized, {})
    address = fallback.get("address")
    latitude = fallback.get("latitude")
    longitude = fallback.get("longitude")
    try:
        request = Request(f"https://api.postalpincode.in/pincode/{normalized}", headers={"User-Agent": "DISASTER_MGM-SIH/1.0"})
        with urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        record = payload[0] if isinstance(payload, list) and payload else {}
        office = (record.get("PostOffice") or [None])[0] if record.get("Status") == "Success" else None
        if office:
            address = ", ".join(filter(None, [office.get("Name"), office.get("District"), office.get("State"), normalized, "India"]))
            search = search_places(address)
            if search.get("results"):
                latitude = search["results"][0]["latitude"]
                longitude = search["results"][0]["longitude"]
    except (HTTPError, URLError, TimeoutError, OSError, KeyError, TypeError, ValueError):
        pass
    if not address:
        return {"pincode": normalized, "address": "PIN found, but an address lookup is unavailable. You can still use the selected map point.", "latitude": latitude, "longitude": longitude, "source": "PIN validation"}
    return {"pincode": normalized, "address": address, "latitude": latitude, "longitude": longitude, "source": "India Post PIN lookup"}


def reverse_geocode(latitude: float, longitude: float) -> dict:
    """Resolve a selected GPS point to a readable address and PIN when available."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Coordinates are outside valid latitude/longitude bounds.")
    global LAST_GEOCODE_AT
    request = Request(
        "https://nominatim.openstreetmap.org/reverse?" + urlencode({"lat": latitude, "lon": longitude, "format": "jsonv2", "zoom": 18, "addressdetails": 1}),
        headers={"User-Agent": "DISASTER_MGM-SIH/1.0 (incident location; contact: local)"},
    )
    try:
        with GEOCODE_LOCK:
            wait_seconds = NOMINATIM_MIN_INTERVAL_SECONDS - (time.monotonic() - LAST_GEOCODE_AT)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            with urlopen(request, timeout=10) as response:
                item = json.loads(response.read().decode("utf-8"))
            LAST_GEOCODE_AT = time.monotonic()
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Address lookup is temporarily unavailable. The exact GPS point can still be submitted.") from error
    address_details = item.get("address", {}) if isinstance(item, dict) else {}
    return {
        "address": item.get("display_name") or f"{latitude:.5f}, {longitude:.5f}",
        "pincode": address_details.get("postcode") or "",
        "latitude": latitude,
        "longitude": longitude,
        "source": "OpenStreetMap reverse geocoding",
    }


def road_route(source_lat: float, source_lon: float, destination_lat: float, destination_lon: float) -> dict:
    """Request a road route from the OSRM service used by the prior sih2 prototype."""
    coordinates = (source_lat, source_lon, destination_lat, destination_lon)
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("Route coordinates must be valid numbers.")
    if not (-90 <= source_lat <= 90 and -90 <= destination_lat <= 90 and -180 <= source_lon <= 180 and -180 <= destination_lon <= 180):
        raise ValueError("Route coordinates are outside valid latitude/longitude bounds.")
    endpoint = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{source_lon},{source_lat};{destination_lon},{destination_lat}"
        "?overview=full&geometries=geojson&steps=false"
    )
    try:
        request = Request(endpoint, headers={"User-Agent": "DISASTER_MGM-SIH-prototype/1.0"})
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        selected = payload.get("routes", [None])[0]
        if not selected or not selected.get("geometry", {}).get("coordinates"):
            raise ValueError("No drivable route is available for these locations.")
        return {
            "provider": "OSRM public routing service",
            "distance_km": round(selected["distance"] / 1000, 2),
            "duration_minutes": max(1, round(selected["duration"] / 60)),
            "geometry": selected["geometry"],
        }
    except ValueError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise RuntimeError("Road routing is temporarily unavailable. Try again shortly.") from error


class DashboardHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 100_000:
                raise ValueError
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("Request body must be a JSON object under 100 KB.")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._set_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        request = urlparse(self.path)
        if request.path == "/":
            self._send_json({"status": "online", "system": "RakshaSetu AI — SIH 26191", "hazards": SUPPORTED_HAZARDS})
            return
        if request.path == "/api/hazards":
            self._send_json({"hazards": SUPPORTED_HAZARDS, "source": "RakshaSetu AI saved ML predictions + synthetic presentation scenarios", "scenarios": hazard_scenarios()})
            return
        if request.path == "/api/scenarios":
            self._send_json({"scenarios": hazard_scenarios()})
            return
        if request.path == "/api/search":
            query = parse_qs(request.query).get("q", [""])[0]
            self._send_json({"query": query, **search_places(query)})
            return
        if request.path == "/api/pincode":
            pin = parse_qs(request.query).get("pin", [""])[0]
            try:
                self._send_json(resolve_pincode(pin))
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if request.path == "/api/reverse-geocode":
            parameters = parse_qs(request.query)
            try:
                result = reverse_geocode(float(parameters["lat"][0]), float(parameters["lon"][0]))
                self._send_json(result)
            except KeyError:
                self._send_json({"error": "lat and lon are required."}, 400)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            except RuntimeError as error:
                self._send_json({"error": str(error)}, 503)
            return
        if request.path == "/api/route":
            parameters = parse_qs(request.query)
            try:
                source_lat, source_lon = float(parameters["source_lat"][0]), float(parameters["source_lon"][0])
                destination_lat, destination_lon = float(parameters["destination_lat"][0]), float(parameters["destination_lon"][0])
                hazard = parameters.get("hazard", ["flood"])[0]
                destination_id = parameters.get("destination_id", [""])[0]
                recommendation = recommend_shelter(source_lat, source_lon, hazard)
                approved = recommendation.get("shelter")
                if not approved:
                    raise ValueError(recommendation.get("reason", "No nearby approved shelter or safe area; route blocked."))
                if destination_id != approved.get("id") or abs(destination_lat - approved["latitude"]) > .0001 or abs(destination_lon - approved["longitude"]) > .0001:
                    raise ValueError("Route blocked: destination is not the nearest approved safe destination for this disaster within 10 km.")
                route = road_route(source_lat, source_lon, destination_lat, destination_lon)
                self._send_json({"status": "success", "route": route})
            except KeyError:
                self._send_json({"error": "source_lat, source_lon, destination_lat, and destination_lon are required."}, 400)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            except RuntimeError as error:
                self._send_json({"error": str(error)}, 503)
            return
        if request.path == "/api/recommend":
            parameters = parse_qs(request.query)
            try:
                recommendation = recommend_shelter(
                    float(parameters["latitude"][0]),
                    float(parameters["longitude"][0]),
                    parameters.get("hazard", ["flood"])[0],
                )
                self._send_json({"status": "success", "recommendation": recommendation})
            except KeyError:
                self._send_json({"error": "latitude and longitude are required."}, 400)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if request.path == "/api/case-studies":
            self._send_json(case_studies())
            return
        if request.path == "/api/recent-disasters":
            self._send_json(recent_disasters())
            return
        if request.path == "/api/authority":
            self._send_json(authority_summary())
            return
        if request.path == "/api/reports":
            self._send_json({"reports": authority_summary()["reports"]})
            return
        if request.path.startswith("/api/case-studies/"):
            try:
                self._send_json(case_study_detail(request.path.rsplit("/", 1)[-1]))
            except ValueError as error:
                self._send_json({"error": str(error)}, 404)
            return
        if request.path == "/api/result":
            parameters = parse_qs(request.query)
            hazard = parameters.get("hazard", ["flood"])[0]
            if hazard not in SUPPORTED_HAZARDS:
                self._send_json({"error": f"hazard must be one of: {', '.join(SUPPORTED_HAZARDS)}"}, 400)
                return
            try:
                self._send_json(main(hazard, parameters.get("area_id", [None])[0]))
            except FileNotFoundError as error:
                self._send_json({"error": str(error)}, 503)
            return
        self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        request = urlparse(self.path)
        try:
            payload = self._read_json_body()
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)
            return
        if request.path == "/api/login":
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", ""))
            with AUTHORITY_LOCK:
                data = _load_authority_data()
                user = next((item for item in data["users"] if item.get("username") == username and item.get("password") == password), None)
            if user is None:
                self._send_json({"error": "Invalid username or password."}, 401)
                return
            self._send_json({"user": _public_user(user)})
            return
        if request.path == "/api/reports":
            try:
                self._send_json({"report": create_report(payload)}, 201)
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return
        if request.path.startswith("/api/reports/") and request.path.endswith("/verify"):
            report_id = request.path.removeprefix("/api/reports/").removesuffix("/verify").strip("/")
            try:
                self._send_json({"report": verify_report(report_id, payload)})
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            except PermissionError as error:
                self._send_json({"error": str(error)}, 403)
            except LookupError as error:
                self._send_json({"error": str(error)}, 404)
            return
        if request.path.startswith("/api/reports/") and request.path.endswith("/review"):
            report_id = request.path.removeprefix("/api/reports/").removesuffix("/review").strip("/")
            try:
                self._send_json({"report": review_report(report_id, payload)})
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            except PermissionError as error:
                self._send_json({"error": str(error)}, 403)
            except LookupError as error:
                self._send_json({"error": str(error)}, 404)
            return
        self._send_json({"error": "Not found"}, 404)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[RakshaSetu API] {format % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), DashboardHandler)
    print("RakshaSetu AI API running at http://127.0.0.1:8000")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
