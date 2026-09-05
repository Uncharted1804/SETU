# Document ID: SPEC-TOL-011
# Title: Process Sensor Tolerance and Spec Limit Reference Table
# Revision: 3

> **SYNC STATUS:** Synchronized with `Spec_Limits` sheet in `sensor_readings.xlsx`
> (P6 deliverable). PT-101 normal band is 80.0 - 150.0 PSI and FT-205 normal band is
> 350.0 - 500.0 GPM.

## Spec Limits and Minimum Wall Thickness Limit

Defines process sensor tolerances and the minimum wall thickness limit for refinery equipment.

| Parameter | Sensor Tag | Unit | Low Limit | High Limit | Notes |
|---|---|---|---|---|---|
| Column Pressure | PT-101 | PSI | 80.0 | 150.0 | Unit 42 column / inlet pressure |
| Furnace Outlet Temp | TT-204 | °C | 15.0 | 85.0 | Applies to preheat train |
| Flow Meter Rate | FT-205 | GPM | 350.0 | 500.0 | Unit 42 flow meter |
| Tank Level | LT-410 | % | 10.0 | 90.0 | TK-12 crude storage |
| Pump Vibration | VT-512 | mm/s | 0.0 | 4.5 | P-330, rotating equipment |
| Minimum Wall Thickness Limit | — | mm | 6.0 | -- | Below this = Priority 1 finding |

A reading outside the Low/High Limit band is classified per SOP-INS-014 as
at minimum a Priority 2 finding, Priority 1 if the deviation exceeds 20%
beyond the limit.
