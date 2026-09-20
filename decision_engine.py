"""Decision layer joining the SIH dashboard to RakshaSetu AI assets."""
from __future__ import annotations

import json
import math
import csv
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_DATASET = PROJECT_ROOT / "RakshaSetu_AI" / "data" / "raw" / "incursions_data.json"
LOCAL_DEMO_DATASET = Path(__file__).resolve().parents[1] / "data" / "raw_data.json"
WEST_BENGAL_DEMO_DATASET = Path(__file__).resolve().parents[1] / "data" / "west_bengal_demo.json"
CASE_STUDIES = PROJECT_ROOT / "RakshaSetu_AI" / "data" / "case_studies" / "case_studies.json"
RECENT_DISASTERS = PROJECT_ROOT / "RakshaSetu_AI" / "data" / "case_studies" / "recent_disaster_profiles.json"
AUTHORITY_DATA = Path(__file__).resolve().parents[1] / "data" / "prototype_authority_data.json"
PROTOTYPE_SCENARIOS = Path(__file__).resolve().parents[1] / "data" / "prototype_hazard_scenarios.json"
SUPPORTED_HAZARDS = ("flood", "earthquake", "landslide", "coastal_erosion", "cloudburst", "cyclone", "road_block", "building_damage", "fire", "medical_emergency", "other")
MAX_SAFE_DESTINATION_DISTANCE_KM = 10.0
# These are prototype safety rules, not an operational incident-command register.
# A destination must be explicitly marked for the reported hazard before it can
# be offered to the router.
HAZARD_DESTINATION_GUIDANCE = {
    "flood": "Elevated, flood-free receiving centre outside drainage channels.",
    "earthquake": "Open assembly area away from buildings, walls and utilities.",
    "landslide": "Stable ground outside slope, debris-flow and drainage run-out paths.",
    "coastal_erosion": "Inland elevated receiving centre beyond the coastal setback.",
    "cloudburst": "High ground outside streams, underpasses and flash-flood paths.",
}
RISK_BY_LABEL = {"Red": 82, "Yellow": 56, "Green": 24}
RELOCATION_RATIO = {"RED": 0.50, "YELLOW": 0.25, "GREEN": 0.0}
VERIFIED_RISK_SCORES = {"High": 90.0, "Moderate": 55.0, "Low": 20.0}


def hazard_scenarios() -> dict[str, Any]:
    """Return the synthetic hazard profiles used to explain the presentation prototype."""
    try:
        data = json.loads(PROTOTYPE_SCENARIOS.read_text(encoding="utf-8"))
        return data.get("scenarios", {}) if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def hazard_profile(hazard: str) -> dict[str, Any]:
    return hazard_scenarios().get(hazard, {})


def _load_dataset() -> dict[str, Any]:
    if WEST_BENGAL_DEMO_DATASET.exists():
        raw = json.loads(WEST_BENGAL_DEMO_DATASET.read_text(encoding="utf-8"))
        habitations = []
        for index, item in enumerate(raw.get("habitations", [])):
            # Varied but explicitly synthetic scores let the statewide prototype
            # demonstrate each layer without claiming live hazard intelligence.
            habitation = {"id": item["id"], "name": item["name"], "lat": item["lat"], "lng": item["lng"], "population": item["population"], "recent_rainfall_mm": 80 + (index % 5) * 24, "soil_saturation": 45 + (index % 4) * 13, "slope_deg": 3 + (index % 6) * 4, "coast_dist_km": 3 + (index % 8) * 5, "elevation_m": 6 + (index % 7) * 9, "drainage_quality": .45 + (index % 4) * .12}
            for hazard in SUPPORTED_HAZARDS:
                score = .34 + ((index * 17 + len(hazard) * 7) % 52) / 100
                habitation[f"{hazard}_risk_score"] = score
                habitation[f"{hazard}_risk"] = "Red" if score >= .70 else "Yellow" if score >= .40 else "Green"
            habitations.append(habitation)
        shelters = [{"id": item["id"], "name": item["name"], "lat": item["lat"], "lng": item["lng"], "capacity": item["capacity"], "safe_for": item["safe_for"], "safety_notes": item["safety_notes"]} for item in raw.get("shelters", [])]
        return {"meta": raw["meta"], "habitations": habitations, "shelters": shelters, "safe_areas": raw.get("safe_areas", []), "model_report": {}}
    if AI_DATASET.exists():
        return json.loads(AI_DATASET.read_text(encoding="utf-8"))
    # Keep the ZIP runnable when the optional adjacent AI project is absent.
    # These deliberately labelled demo records are not real shelter directions.
    raw = json.loads(LOCAL_DEMO_DATASET.read_text(encoding="utf-8"))
    habitations = []
    for item in raw.get("areas", []):
        risk = float(item.get("flood_risk", 0)) / 100
        habitation = {"id": item["id"], "name": item["name"], "lat": item["latitude"], "lng": item["longitude"], "population": item["population"], "recent_rainfall_mm": 130, "soil_saturation": 62, "slope_deg": 4, "coast_dist_km": 12, "elevation_m": 9, "drainage_quality": .55}
        for hazard in SUPPORTED_HAZARDS:
            habitation[f"{hazard}_risk_score"] = risk
            habitation[f"{hazard}_risk"] = "Red" if risk >= .7 else "Yellow" if risk >= .4 else "Green"
        habitations.append(habitation)
    shelters = [{"id": item["id"], "name": item["name"], "lat": item["latitude"], "lng": item["longitude"], "capacity": item["capacity"], "safe_for": item.get("safe_for", []), "safety_notes": item.get("safety_notes", "Prototype receiving centre — verify status before use.")} for item in raw.get("shelters", [])]
    return {"meta": {"region": raw.get("location", "Prototype demonstration area")}, "habitations": habitations, "shelters": shelters, "safe_areas": raw.get("safe_areas", []), "model_report": {}}


def case_studies() -> dict[str, Any]:
    """Return provenance-only metadata for optional external case studies."""
    if not CASE_STUDIES.exists():
        return {"case_studies": []}
    return json.loads(CASE_STUDIES.read_text(encoding="utf-8"))


def recent_disasters() -> dict[str, Any]:
    if not RECENT_DISASTERS.exists():
        return {"events": []}
    return json.loads(RECENT_DISASTERS.read_text(encoding="utf-8"))


def case_study_detail(case_study_id: str) -> dict[str, Any]:
    """Load only the portable, presentation-safe records for a case study."""
    registry = case_studies()
    study = next((item for item in registry["case_studies"] if item["id"] == case_study_id), None)
    if study is None:
        raise ValueError(f"Unknown case study: {case_study_id}")
    root = CASE_STUDIES.parent / case_study_id
    if case_study_id == "nepal_flood_2026":
        with (root / "processed" / "nepal_multi_hazard_dataset.csv").open(encoding="utf-8", newline="") as file:
            points = [{"id": row["location_id"], "name": row["location_id"], "latitude": float(row["latitude"]), "longitude": float(row["longitude"]), "hazard": row["hazard_type"], "source": row["data_source"], "quality": row["data_quality"]} for row in csv.DictReader(file)]
        safety = json.loads((root / "emergency" / "safe_shelter_zone_status.json").read_text(encoding="utf-8"))
        buildings = json.loads((root / "infrastructure" / "buildings.geojson").read_text(encoding="utf-8"))
        candidates = []
        for feature in buildings["features"]:
            properties = feature.get("properties", {})
            kind = str(properties.get("amenity") or properties.get("building") or "").lower()
            if kind not in {"school", "college", "community_centre", "community_center", "civic"}:
                continue
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates", [])
            while coordinates and isinstance(coordinates[0], list) and coordinates and isinstance(coordinates[0][0], list):
                coordinates = coordinates[0]
            if not coordinates:
                continue
            longitude, latitude = coordinates if isinstance(coordinates[0], (int, float)) else coordinates[0]
            candidates.append({
                "id": feature["id"], "name": properties.get("name") or f"{kind.replace('_', ' ').title()} assessment candidate",
                "latitude": latitude, "longitude": longitude, "facility_type": kind,
                "status": "ASSESSMENT CANDIDATE — NOT A VERIFIED SAFE SHELTER",
            })
        return {**study, "points": points, "shelter_candidates": candidates, "verified_shelters": [],
                "safety_guidance": safety["message"], "shelter_action": "Assess candidate facilities with the listed mandatory checks before authorising a route or allocation."}
    volcano = json.loads((root / "volcano" / "volcano_information.json").read_text(encoding="utf-8"))
    point = {"id": volcano["volcano_id"], "name": volcano["volcano_name"], "latitude": volcano["latitude"], "longitude": volcano["longitude"], "hazard": "volcanic_eruption", "source": "Smithsonian Global Volcanism Program", "quality": volcano["data_quality"]}
    return {**study, "points": [point], "shelter_candidates": [], "verified_shelters": [],
            "alert_level": volcano["alert_level_at_source_publication"], "safety_guidance": "The official 3 km activity exclusion zone is provided as a GIS layer. Confirm current PVMBG advisories before any operational use.",
            "shelter_action": "No shelter inventory was supplied. Obtain an incident-command-approved shelter register before suggesting facilities or routes."}


def _risk_level(score: float) -> str:
    return "RED" if score >= 70 else "YELLOW" if score >= 40 else "GREEN"


def _distance_km(a: dict[str, Any], b: dict[str, Any]) -> float:
    lat1, lon1 = math.radians(a["latitude"]), math.radians(a["longitude"])
    lat2, lon2 = math.radians(b["latitude"]), math.radians(b["longitude"])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _area_from_habitation(habitation: dict[str, Any], hazard: str) -> dict[str, Any]:
    """Combine saved ML classification with its local hazard-intensity score."""
    model_label = habitation.get(f"{hazard}_model_pred") or habitation.get(f"{hazard}_risk", "Green")
    raw_score = habitation.get(f"{hazard}_risk_score")
    if hazard == "coastal_erosion":
        # The bundled data has coast distance and elevation, but no shoreline
        # change series. Keep this explicitly synthetic for the presentation.
        coast_exposure = max(0.0, 1.0 - min(float(habitation.get("coast_dist_km", 30)) / 30.0, 1.0))
        low_elevation = max(0.0, 1.0 - min(float(habitation.get("elevation_m", 20)) / 20.0, 1.0))
        raw_score = coast_exposure * 0.72 + low_elevation * 0.28
        model_label = "Red" if raw_score >= .70 else "Yellow" if raw_score >= .40 else "Green"
    elif hazard == "landslide":
        # Keep the saved landslide score, but add a transparent slope/saturation
        # proxy so the presentation contains a visible unstable red hillside.
        slope = min(float(habitation.get("slope_deg", 0)) / 12.0, 1.0)
        saturation = min(float(habitation.get("soil_saturation", 0)) / 100.0, 1.0)
        rainfall = min(float(habitation.get("recent_rainfall_mm", 0)) / 220.0, 1.0)
        proxy_score = slope * .45 + saturation * .35 + rainfall * .20
        raw_score = max(float(raw_score or 0), proxy_score)
        model_label = "Red" if raw_score >= .70 else "Yellow" if raw_score >= .40 else "Green"
    elif hazard == "cloudburst":
        # Short-duration extreme rain proxy: recent rainfall, saturated soil,
        # poor drainage and steep slopes from the prototype dataset.
        rainfall = min(float(habitation.get("recent_rainfall_mm", 0)) / 220.0, 1.0)
        saturation = min(float(habitation.get("soil_saturation", 0)) / 100.0, 1.0)
        drainage = 1.0 - min(float(habitation.get("drainage_quality", 1)), 1.0)
        slope = min(float(habitation.get("slope_deg", 0)) / 30.0, 1.0)
        raw_score = rainfall * .40 + saturation * .25 + drainage * .20 + slope * .15
        model_label = "Red" if raw_score >= .70 else "Yellow" if raw_score >= .40 else "Green"
    if raw_score is None:
        raw_score = RISK_BY_LABEL.get(model_label, 0) / 100
    score = round(max(float(raw_score) * 100, RISK_BY_LABEL.get(model_label, 0)), 1)
    level = _risk_level(score)
    return {
        "id": habitation["id"], "name": habitation["name"],
        "latitude": habitation["lat"], "longitude": habitation["lng"],
        "population": habitation["population"], "risk": score, "risk_score": score,
        "risk_level": level, "zone": level, "model_prediction": model_label,
        "relocation_population_required": math.ceil(habitation["population"] * RELOCATION_RATIO[level]),
        "drivers": {
            "recent_rainfall_mm": habitation.get("recent_rainfall_mm"),
            "soil_saturation": habitation.get("soil_saturation"),
            "slope_deg": habitation.get("slope_deg"),
            "coast_dist_km": habitation.get("coast_dist_km"),
            "elevation_m": habitation.get("elevation_m"),
            "drainage_quality": habitation.get("drainage_quality"),
        },
    }


def _shelters(raw_shelters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": item["id"], "name": item["name"], "latitude": item["lat"], "longitude": item["lng"], "capacity": item["capacity"], "available_capacity": item["capacity"], "allocations": [], "safe_for": item.get("safe_for", list(SUPPORTED_HAZARDS)), "safety_notes": item.get("safety_notes", "Prototype receiving centre — verify status before use."), "destination_type": "shelter"} for item in raw_shelters]


def _safe_areas(raw_safe_areas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": item["id"], "name": item["name"], "latitude": item["lat"], "longitude": item["lng"], "capacity": item.get("capacity", 0), "available_capacity": item.get("capacity", 0), "safe_for": item.get("safe_for", []), "safety_notes": item.get("safety_notes", "Prototype safe area — verify status before use."), "destination_type": "safe_area"} for item in raw_safe_areas]


def _destination_recommendation(source: dict[str, Any], shelters: list[dict[str, Any]], safe_areas: list[dict[str, Any]], hazard: str) -> dict[str, Any]:
    """Return only a nearby, hazard-approved shelter or fallback safe area.

    No destination means no route: this prevents the UI from drawing a path to
    an unsuitable facility merely because it is geographically close.
    """
    def nearby(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        approved = []
        for item in items:
            if hazard not in item.get("safe_for", []):
                continue
            distance = _distance_km(source, item)
            if distance <= MAX_SAFE_DESTINATION_DISTANCE_KM and item.get("available_capacity", 0) > 0:
                approved.append({**item, "distance_km": round(distance, 2)})
        return sorted(approved, key=lambda item: (item["distance_km"], -item.get("available_capacity", 0)))

    nearby_shelters = nearby(shelters)
    if nearby_shelters:
        destination = nearby_shelters[0]
        return {"destination": destination, "route": _route(source, destination), "status": "shelter_found", "reason": f"Nearby shelter approved for {hazard.replace('_', ' ')}: {destination['safety_notes']}", "candidates": nearby_shelters[:5]}
    nearby_safe_areas = nearby(safe_areas)
    if nearby_safe_areas:
        destination = nearby_safe_areas[0]
        return {"destination": destination, "route": _route(source, destination), "status": "safe_area_fallback", "reason": f"No approved shelter is available within {MAX_SAFE_DESTINATION_DISTANCE_KM:g} km. Routing only to the nearby {hazard.replace('_', ' ')} safe area: {destination['safety_notes']}", "candidates": nearby_safe_areas[:5]}
    return {"destination": None, "route": None, "status": "no_safe_destination", "reason": f"No approved shelter or {hazard.replace('_', ' ')} safe area is available within {MAX_SAFE_DESTINATION_DISTANCE_KM:g} km. No route has been generated to avoid an unsafe or unsuitable path.", "candidates": []}


def _verified_risk_overrides() -> dict[str, Any]:
    """Load field-verified overrides saved by the local prototype authority workflow."""
    try:
        data = json.loads(AUTHORITY_DATA.read_text(encoding="utf-8"))
        return data.get("risk_overrides", {}) if isinstance(data.get("risk_overrides"), dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _authority_reports() -> list[dict[str, Any]]:
    try:
        data = json.loads(AUTHORITY_DATA.read_text(encoding="utf-8"))
        reports = data.get("reports", []) if isinstance(data, dict) else []
        return reports if isinstance(reports, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _active_report(report: dict[str, Any]) -> bool:
    return report.get("status") not in {"Cancelled", "Rejected as fake"}


def _report_area(report: dict[str, Any], areas: list[dict[str, Any]], max_distance_km: float = 15) -> dict[str, Any] | None:
    location_id = str(report.get("location_id") or "").strip()
    if location_id:
        match = next((area for area in areas if area["id"] == location_id), None)
        if match:
            return match
    location = str(report.get("location") or "").strip().casefold()
    if location:
        match = next((area for area in areas if area["name"].casefold() == location), None)
        if match:
            return match
    try:
        point = {"latitude": float(report["latitude"]), "longitude": float(report["longitude"])}
    except (KeyError, TypeError, ValueError):
        return None
    nearest = min(areas, key=lambda area: _distance_km(point, area), default=None)
    return nearest if nearest and _distance_km(point, nearest) <= max_distance_km else None


def _apply_community_reports(areas: list[dict[str, Any]], hazard: str) -> None:
    """Add report counts and immediate community high-risk signals to map areas.

    A trusted 4/5 community rating or four corroborating nearby reports can
    create an immediate red incident. Field verification can later confirm or
    close that signal through the authority workflow.
    """
    reports = [report for report in _authority_reports() if _active_report(report) and report.get("hazard") == hazard]
    for area in areas:
        area["community_report_count"] = 0
        area["incident_count"] = 0
    dynamic = []
    for report in reports:
        area = _report_area(report, areas)
        if area:
            area["community_report_count"] += 1
            area["incident_count"] += 1
            if report.get("final_risk") == "High" and report.get("auto_high"):
                area.update({
                    "risk": 90.0,
                    "risk_score": 90.0,
                    "risk_level": "RED",
                    "zone": "RED",
                    "model_prediction": "Community reports: High",
                    "relocation_population_required": math.ceil(area["population"] * RELOCATION_RATIO["RED"]),
                    "community_high_risk": True,
                })
            continue
        if report.get("final_risk") != "High" or not report.get("auto_high"):
            continue
        try:
            latitude, longitude = float(report["latitude"]), float(report["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        dynamic_id = f"CR-{report.get('id', 'incident')}"
        if any(item["id"] == dynamic_id for item in dynamic):
            continue
        dynamic.append({
            "id": dynamic_id,
            "name": f"{report.get('location') or 'Community incident'} (reported)",
            "latitude": latitude,
            "longitude": longitude,
            "population": int(report.get("affected_people") or 100),
            "risk": 90.0,
            "risk_score": 90.0,
            "risk_level": "RED",
            "zone": "RED",
            "model_prediction": "Community reports: High",
            "relocation_population_required": int(report.get("affected_people") or 100),
            "drivers": {"incident_type": report.get("incident_type"), "community_report_count": 1},
            "community_report_count": 1,
            "incident_count": 1,
            "community_high_risk": True,
        })
    areas.extend(dynamic)


def _apply_verified_overrides(areas: list[dict[str, Any]], hazard: str) -> None:
    overrides = _verified_risk_overrides()
    for area in areas:
        override = overrides.get(area["id"])
        if not override or override.get("hazard") != hazard:
            continue
        verified_risk = override.get("final_risk")
        score = VERIFIED_RISK_SCORES.get(verified_risk)
        if score is None:
            continue
        level = _risk_level(score)
        area.update({
            "risk": score,
            "risk_score": score,
            "risk_level": level,
            "zone": level,
            "model_prediction": "Community reports: High" if override.get("auto_high") else f"Field verified: {verified_risk}",
            "relocation_population_required": math.ceil(area["population"] * RELOCATION_RATIO[level]),
            "field_verified_override": {
                "report_id": override.get("report_id"),
                "verified_by": override.get("verified_by"),
                "final_risk": verified_risk,
                "verified_at": override.get("verified_at"),
            },
        })


def _allocate(areas: list[dict[str, Any]], shelters: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    assignments, unmet = [], []
    for area in sorted(areas, key=lambda item: (-item["risk_score"], -item["population"])):
        remaining = area["relocation_population_required"]
        for shelter in sorted(shelters, key=lambda item: _distance_km(area, item)):
            if remaining <= 0:
                break
            allocated = min(remaining, shelter["available_capacity"])
            if not allocated:
                continue
            distance = round(_distance_km(area, shelter), 2)
            shelter["available_capacity"] -= allocated
            shelter["allocations"].append({"area_id": area["id"], "people_assigned": allocated})
            assignments.append({"area_id": area["id"], "area_name": area["name"], "shelter_id": shelter["id"], "shelter_name": shelter["name"], "people_assigned": allocated, "distance_km": distance})
            remaining -= allocated
        if remaining:
            unmet.append({"area_id": area["id"], "area_name": area["name"], "people_not_allocated": remaining})
    return assignments, unmet


def _route(source: dict[str, Any], shelter: dict[str, Any]) -> dict[str, Any]:
    distance = round(_distance_km(source, shelter), 2)
    coordinates = [[source["longitude"], source["latitude"]], [shelter["longitude"], source["latitude"]], [shelter["longitude"], shelter["latitude"]]]
    return {"distance_km": distance, "duration_minutes": max(1, round(distance / 25 * 60)), "geometry": {"coordinates": coordinates}}


def recommend_shelter(latitude: float, longitude: float, hazard: str = "flood") -> dict[str, Any]:
    """Rank the supplied shelter register for an arbitrary geocoded source point.

    This reuses the saved RakshaSetu hazard classifications and shelter inventory;
    it does not invent a risk zone for a place that is only a map lookup.
    """
    if hazard not in SUPPORTED_HAZARDS:
        hazard = "flood"
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Source coordinates are outside valid latitude/longitude bounds.")
    dataset = _load_dataset()
    areas = [_area_from_habitation(item, hazard) for item in dataset["habitations"]]
    _apply_verified_overrides(areas, hazard)
    _apply_community_reports(areas, hazard)
    source = {"id": "map-source", "name": "Selected map location", "latitude": latitude, "longitude": longitude}
    recommendation = _destination_recommendation(source, _shelters(dataset["shelters"]), _safe_areas(dataset.get("safe_areas", [])), hazard)
    return {
        "source": source,
        "shelter": recommendation["destination"],
        "candidates": recommendation["candidates"],
        "route": recommendation["route"],
        "status": recommendation["status"],
        "reason": recommendation["reason"],
        "hazard": hazard,
    }


def main(hazard: str = "flood", area_id: str | None = None) -> dict[str, Any]:
    if hazard not in SUPPORTED_HAZARDS:
        hazard = "flood"
    dataset = _load_dataset()
    areas, shelters = ([_area_from_habitation(item, hazard) for item in dataset["habitations"]], _shelters(dataset["shelters"]))
    safe_areas = _safe_areas(dataset.get("safe_areas", []))
    _apply_verified_overrides(areas, hazard)
    _apply_community_reports(areas, hazard)
    assignments, unmet = _allocate(areas, shelters)
    source = next((item for item in areas if item["id"] == area_id), None) if area_id else None
    source = source or max(areas, key=lambda item: item["risk_score"])
    recommendation = _destination_recommendation(source, _shelters(dataset["shelters"]), safe_areas, hazard)
    total_need, total_assigned = sum(item["relocation_population_required"] for item in areas), sum(item["people_assigned"] for item in assignments)
    return {
        "status": "success", "disaster": hazard, "hazard": hazard, "hazard_name": hazard.upper(),
        "region": dataset.get("meta", {}).get("region", "RakshaSetu demonstration area"), "source_area": source,
        "zones": areas, "shelters": shelters, "safe_areas": safe_areas, "recommended_shelter": recommendation["destination"], "route": recommendation["route"], "route_status": recommendation["status"], "route_reason": recommendation["reason"], "maximum_safe_destination_distance_km": MAX_SAFE_DESTINATION_DISTANCE_KM,
        "relocation_plan": {"total_population_requiring_relocation": total_need, "people_allocated": total_assigned, "people_unallocated": total_need - total_assigned, "shelter_assignments": assignments, "unallocated_needs": unmet},
        "ai_model": {"source": "RakshaSetu AI saved ML predictions + local community report signals", "hazard": hazard, "metrics": dataset.get("model_report", {}).get(hazard, {})},
        "hazard_profile": hazard_profile(hazard),
        "prototype_notice": "Presentation prototype: synthetic hazard scenarios and local report signals. Replace with authoritative GIS, weather and incident feeds before operational use.",
    }
