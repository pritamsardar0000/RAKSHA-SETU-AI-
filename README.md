# RakshaSetu AI — SIH 26191 Dashboard

Integrated hackathon prototype for **Problem Statement 26191**: Intelligent Identification of Hazard-Based Red Zones, Carrying Capacity Assessment, and Immediate Relocation Needs for Vulnerable Habitations.

The React GIS dashboard from `SIH` now uses the hazard records and saved ML classifications in the adjacent `RakshaSetu_AI` project. It displays flood, earthquake, landslide, coastal-erosion and cloudburst zones; derives relocation priority; allocates people to available shelters; and recommends an evacuation route. The last two are clearly labelled synthetic presentation scenarios in [prototype_hazard_scenarios.json](data/prototype_hazard_scenarios.json).

## Included case studies

Two supplementary, source-attributed datasets are included under `RakshaSetu_AI/data/case_studies`. They are not mixed into the India demonstration dashboard, preventing a false geographic or model-data claim.

- `nepal_flood_2026`: flood, flash-flood, landslide and debris-flow case-study layers, including OpenStreetMap infrastructure, NASA POWER weather values, and BIPAD historical-event metadata.
- `indonesia_volcano_2026`: volcano-risk case-study materials, including the Anak Krakatau exclusion-zone workflow and its source documentation.

See `GET /api/case-studies` while the backend is running for their provenance summary. Retain the attribution and limitations stored with each package before redistribution.

## Run

For a double-click start on Windows, run [START_DISASTER_MGM.cmd](START_DISASTER_MGM.cmd). It launches the local API and Vite interface, then opens the browser.

From `C:\\sih_2026\\SIH`:

```powershell
py -3.15 backend\api.py
```

In a second PowerShell window:

```powershell
cd frontend
npm run dev
```

Open the Vite address printed by the second command (normally `http://localhost:5173`). Keep `RakshaSetu_AI` beside `SIH`; its `data/raw/incursions_data.json` is the AI/GIS data source.

The top search field has three result groups: **Project locations & shelters** are the prototype's India AI/GIS records; **Imported case studies** opens the supplied Nepal or Indonesia datasets; and **Map locations** are general India, Nepal and Indonesia place results from OpenStreetMap Nominatim. Search `Nepal`, `Rasuwa`, `Indonesia`, `Anak Krakatau`, or `volcano` to open the matching imported case study. The **Case Studies** sidebar item gives the same access.

Use the **Source / Destination** selector beside the search field before choosing a normal map result. Shelter markers and the Shelters page always set the destination; red-zone markers set the source. With auto-run disabled, the map stays clear until **Recalculate Route** is pressed; either mode requests a road route from OSRM. Nepal and Indonesia reference points can be viewed on the map, but are explicitly not used to create a shelter recommendation or evacuation route because their packages do not contain a verified operational shelter register.

The Live Map & Zones page has its own search control. With **Auto-run safest route** enabled, selecting a source and destination immediately requests the nearest shelter ranking and road route through the local backend. Double-clicking **Recalculate Route** enables this instant mode.

The geocoding and routing calls go through the local backend, which supplies the required service headers, limits Nominatim requests to one per second, caches completed location searches, and returns clear errors for no results or unavailable network services. Internet access is required for new map searches and road routing.

## Community and field reports

Choose **Report Disaster** in the sidebar to submit a local-user incident report, or **Field Officer Report** to include severity plus field verification/recommended action. Reports require a valid six-digit Indian area PIN and an exact map/GPS point; **Find address** resolves the PIN through the local API and India Post lookup. Reports are stored in `data/prototype_authority_data.json` for the local review workflow. A community rating of 4 or 5 immediately creates a High-risk signal (and four corroborating nearby reports do the same); the field officer can validate, downgrade, cancel or reject that signal afterward.

The dashboard distinguishes **Shelter Capacity** (the total number of places) from **currently open capacity**. In the supplied flood scenario, all 11,456 places are allocated by the demonstration plan, so open capacity correctly reads zero while total capacity remains visible.

## Prototype authority workflow

When **Use current GPS** is selected, the UI also attempts reverse geocoding so the current address and PIN can be shown in the report before submission.

The local authority store is [prototype_authority_data.json](data/prototype_authority_data.json). It provides demo users plus persistent report and risk-override data for the presentation:

- Admin: `admin_demo` / `admin123`
- Field officer: `field_demo` / `field123`

It also contains one preloaded, verified Nabinpur example so the authority dashboard demonstrates a persisted decision immediately.

Submit a community report using **Report Disaster**, preferably through **Report at this location**, **Use current GPS**, or **Pick on map** so it is linked to a known demo zone or creates a clearly labelled reported incident point. Sign in, open the Admin or Officer Dashboard, select **Verify report**, choose High, Moderate, or Low, and record the verification decision. The backend writes a risk override to the JSON store. On refresh, the matched zone’s score, colour, relocation requirement, incident count and alert listing update. Incident counts by category are shown in **Incidents**.

These credentials, JSON records, and local APIs are intended for the hackathon presentation and are not secure production identity or incident-management systems.

## Prototype boundary

This is a hackathon demonstration built with included synthetic/demo data and saved model outputs. It must be connected to authoritative GIS, weather, population and road-network feeds, then validated by disaster-management authorities before operational use.
