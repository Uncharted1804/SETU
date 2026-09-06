# KB Retrieval Test Queries (T-3 validation)

Run each query through `kb_search(query, k=5)`. Pass condition: the expected
doc_id appears in the top 3 results, and no decoy doc (36-40) appears in the
top 3 for any of these.

| # | Query | Expected top result(s) |
|---|---|---|
| 1 | "hydrotest acceptance criteria" | 03_hydrotest_acceptance_criteria |
| 2 | "what is the minimum wall thickness limit" | 04_spec_tolerance_table, 02_inspection_sop_pressure_vessel |
| 3 | "confined space entry H2S alarm level" | 08_confined_space_entry_procedure |
| 4 | "relief valve set pressure drift tolerance" | 18_relief_valve_testing_procedure, 11_vendor_letter_relief_valve |
| 5 | "gasket recall above 70 degrees" | 14_vendor_recall_gasket |
| 6 | "ultrasonic thickness gauge calibration frequency" | 15_calibration_procedure_ut_gauge |
| 7 | "hot work permit requirements near tank farm" | 07_hot_work_permit_policy |
| 8 | "corrosion under insulation inspection interval" | 05_corrosion_under_insulation_guideline |
| 9 | "radiography acceptance criteria for pipe welds" | 16_ndt_radiography_procedure |
| 10 | "FCC catalyst performance and pricing" | 12_vendor_letter_fcc_catalyst, 26_vendor_negotiation_budget_letter |
| 11 | "heat exchanger tube plugging criteria" | 32_heat_exchanger_tube_bundle_procedure, 20_audit_history_heat_exchanger |
| 12 | "sulphur recovery unit efficiency" | 34_sulphur_recovery_unit_operating_note |
| 13 | "confidential capacity expansion assessment" | 27_confidential_strategy_memo_capacity_expansion |
| 14 | "example approval note format for return to service" | 25_approval_note_example_past |

## Discrimination check (should NOT surface in top-3 for the above)
- 36_decoy_hr_leave_policy
- 37_decoy_it_password_policy
- 38_decoy_travel_policy
- 39_decoy_cafeteria_facilities_notice
- 40_decoy_marketing_brochure

## If a query fails
Most likely cause is chunking, not embedding quality:
- Check whether the relevant sentence got split across a chunk boundary
  (see CHUNK_SIZE/CHUNK_OVERLAP in ingest_chroma.py)
- Check the doc actually contains vocabulary matching the query
- If a decoy surfaces, it usually means two docs share generic phrasing —
  tighten the query or the doc content
