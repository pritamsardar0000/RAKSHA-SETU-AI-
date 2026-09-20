import json
from pathlib import Path


# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DATA = BASE_DIR / "data" / "raw_data.json"
PROCESSED_DATA = BASE_DIR / "data" / "processed_data.json"


def get_risk_level(risk):
    if risk >= 70:
        return "RED"
    elif risk >= 40:
        return "YELLOW"
    else:
        return "GREEN"


def process_data():
    # Read raw GEO / other data
    with open(RAW_DATA, "r", encoding="utf-8") as file:
        data = json.load(file)

    processed_areas = []

    # Process each area
    for area in data["areas"]:
        risk = area["flood_risk"]

        processed_area = {
            "id": area["id"],
            "name": area["name"],
            "latitude": area["latitude"],
            "longitude": area["longitude"],
            "population": area["population"],
            "risk_score": risk,
            "risk_level": get_risk_level(risk)
        }

        processed_areas.append(processed_area)

    # Process shelters
    processed_shelters = []

    for shelter in data["shelters"]:
        processed_shelter = {
            "id": shelter["id"],
            "name": shelter["name"],
            "latitude": shelter["latitude"],
            "longitude": shelter["longitude"],
            "capacity": shelter["capacity"],
            "current_population": 0,
            "available_capacity": shelter["capacity"]
        }

        processed_shelters.append(processed_shelter)

    # Final structured data
    result = {
        "disaster": data["disaster"],
        "areas": processed_areas,
        "shelters": processed_shelters
    }

    # Save JSON
    with open(PROCESSED_DATA, "w", encoding="utf-8") as file:
        json.dump(result, file, indent=2)

    print("Data processing completed.")
    print(f"Processed data saved to: {PROCESSED_DATA}")


if __name__ == "__main__":
    process_data()