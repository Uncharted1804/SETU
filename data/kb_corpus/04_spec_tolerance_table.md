# Document ID: SPEC-TOL-011
# Title: Process Sensor Tolerance and Spec Limit Reference Table
# Revision: 3

> **SYNC REQUIRED:** These values must be identical to the `Spec_Limits`
> sheet in `sensor_readings.xlsx` (owned by P6). If P6 changes the workbook,
> edit this document to match, or the reasoning agent's grounding check will
> contradict the spreadsheet on stage. Placeholder values — confirm final
> agreed numbers before demo freeze.

## Spec Limits and Minimum Wall Thickness Limit

Defines process sensor tolerances and the minimum wall thickness limit for refinery equipment.

| Parameter | Sensor Tag | Unit | Low Limit | High Limit | Notes |
|---|---|---|---|---|---|
| Column Pressure | PT-101 | bar | 8.0 | 12.0 | C-101 top pressure |
| Furnace Outlet Temp | TT-204 | °C | 15.0 | 85.0 | Applies to preheat train |
| Crude Feed Flow | FT-330 | L/min | 50.0 | 300.0 | To C-101 charge pump P-330 |
| Tank Level | LT-410 | % | 10.0 | 90.0 | TK-12 crude storage |
| Pump Vibration | VT-512 | mm/s | 0.0 | 4.5 | P-330, rotating equipment |
| Minimum Wall Thickness Limit | — | mm | 6.0 | -- | Below this = Priority 1 finding |

A reading outside the Low/High Limit band is classified per SOP-INS-014 as
at minimum a Priority 2 finding, Priority 1 if the deviation exceeds 20%
beyond the limit.
