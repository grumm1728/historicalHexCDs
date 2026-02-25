# Historical U.S. Polyhex Timeline

Interactive timeline for U.S. congressional polyhex maps in a **single composite view**.

- Each frame is one Congress.
- Polyhex cells are rendered directly as the map (clipped-polyhex visual mode).
- Current sample includes Congress 118 from `HexCDv31.*`.

## Important local-run note

Opening `web/index.html` directly (`file://...`) will not work because browsers block `fetch` from local files.

Run a local server instead:

```powershell
python -m http.server 8000 --directory web
```

Then open `http://localhost:8000`.

## Setup

```powershell
python -m pip install -r requirements.txt
npm install
```

## Build data + staged web assets

```powershell
python scripts/build_web_assets.py
```

Or:

```powershell
npm run build:web
```

## Add more Congress frames

Add shapefiles under:

`data_raw/congress/<congress_number>/HexCDv31.shp` (plus `.shx/.dbf/.prj`)

Then rebuild.

## GitHub Pages

A workflow is included at `.github/workflows/pages.yml`.

### First-time repo publish steps

If this folder is not yet a git repo:

```powershell
git init
git add .
git commit -m "Initial historical polyhex timeline"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

Then in GitHub:

1. Go to `Settings -> Pages`
2. Set `Source` to `GitHub Actions`
3. Push to `main` (or rerun the workflow)

Workflow build/deploy will publish `web/` as the Pages site.

## Implemented outputs

- `data_processed/congress_index.json`
- `data_processed/polyhex_by_congress/<congress>.geojson`
- `web/data_processed/*` (staged for hosting)

## Date handling

Congress dates are generated with historical term rules:

- Congress 1-73 start on March 4
- Congress 74+ start on January 3
