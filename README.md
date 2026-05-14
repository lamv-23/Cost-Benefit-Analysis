# Transport Cost-Benefit Analysis Dashboard

A Streamlit-based cost-benefit analysis tool implementing the **TfNSW Economic Parameter Values (January 2025, June 2024 prices)** framework for transport project appraisal.

## Features

- Multi-vehicle-type, multi-project-case CBA (Car, LCV, HCV, Bus)
- Benefit categories: Travel Time Savings, Reliability, VOC, Safety, Environment, Active Transport, Pavement Savings
- Discounted cash flow with custom evaluation periods and discount rates
- Monte Carlo risk simulation (Normal, Lognormal, Triangular distributions)
- Sensitivity analysis: discount rate, carbon price, VSL, WEBs
- File import (CSV, Excel) with template download, smart parse, and user mapping
- Per-case safety cost rates (General or Detailed mode)
- TfNSW-compliant parameter values, user-editable

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

The app opens at `http://localhost:8501`.

## Data Entry

1. **Sidebar**: Set project name, context (urban/rural), evaluation period, discount rate, modelling years, and annualisation parameters
2. **Data Input tab**: Enter VHT, VKT, and Demand per vehicle type per modelling year for base case and project alternatives
3. **Optional**: Import data from CSV or Excel using the template or smart parse feature
4. **Dashboard tab**: View NPV, BCR, IRR, payback period, and benefit composition charts
5. **Cashflow tab**: Detailed year-by-year discounted cash flow table
6. **Sensitivity tab**: Monte Carlo, carbon price, VSL, and WEBs sensitivity analysis
7. **Parameters tab**: Edit all TfNSW economic parameter values (VTTS, VOC, occupancy, crash costs, etc.)

## Benefit Calculation Conventions

| Benefit | Input | Method |
|---------|-------|--------|
| **TTS** | VHT delta | VHT saving x occupancy x VTTS ($/person-hr) |
| **Reliability** | Derived | 30% x TTS x reliability ratio |
| **VOC** | VKT delta | VKT x VOC rate (speed-dependent, interpolated) |
| **Safety** | VKT delta | VKT delta x safety $/VKT rate per vehicle type |
| **Environment** | VKT delta | VKT delta x (emission + air pollution + noise) $/VKT |
| **Active Transport** | Walk/cycle km | Distance x health benefit rate ($/person-km) |
| **Pavement** | Annual | Fixed annual saving, not indexed |

All benefits are incremental (project minus base). Discounting uses start-of-year convention.

## Deployment

### Streamlit Community Cloud

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repo and deploy

### Docker

```bash
docker build -t cba-dashboard .
docker run -p 8501:8501 cba-dashboard
```

### Azure Container Apps

```bash
docker build -t cba-dashboard .
docker tag cba-dashboard <your-registry>.azurecr.io/cba-dashboard:latest
docker push <your-registry>.azurecr.io/cba-dashboard:latest
# Then create/update the Container App with the image
```

## Parameter Sources

- Value of Travel Time Savings: TfNSW EPV Jan 2025, Table 3
- Vehicle Operating Costs: TfNSW EPV Jan 2025, speed-dependent lookup tables
- Crash costs: TfNSW EPV Jan 2025, blended $/VKT rates
- Carbon price: $123/tCO₂e (TfNSW EPV Jan 2025, June 2024 prices)
- Air pollution and noise: TfNSW EPV Jan 2025, per vehicle type per context
- Occupancy: TfNSW EPV (urban) and ATAP PV2 (rural)

## Limitations

- Crash analysis uses blended $/VKT rates. Per-severity crash data entry is available but not yet wired into the calculation engine.
- Wider Economic Benefits (WEBs) are shown as a sensitivity range and are **not included** in the primary BCR/NPV.
- VOC speed tables are currently read-only (not user-editable).
- Construction costs are spread evenly over the construction period (no year-by-year schedule).
- Stops data is collected for reference but does not affect calculations.

## Roadmap

- [ ] Save/Load Project: JSON export/import including inputs, results, and Monte Carlo outputs
- [ ] Per-severity crash calculation engine
- [ ] Editable VOC speed tables
- [ ] Year-by-year construction cost scheduling
- [ ] Azure Blob Storage integration for project persistence

## License

Internal use — TfNSW Economic Parameter Values framework.