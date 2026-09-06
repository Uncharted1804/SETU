import pytest
from app.config import get_settings
from app.tools.kb import KnowledgeBase

CALIBRATION_QUERIES = [
    (1, "hydrotest acceptance criteria", ["03_hydrotest_acceptance_criteria"]),
    (2, "what is the minimum wall thickness limit", ["04_spec_tolerance_table", "02_inspection_sop_pressure_vessel"]),
    (3, "confined space entry H2S alarm level", ["08_confined_space_entry_procedure"]),
    (4, "relief valve set pressure drift tolerance", ["18_relief_valve_testing_procedure", "11_vendor_letter_relief_valve"]),
    (5, "gasket recall above 70 degrees", ["14_vendor_recall_gasket"]),
    (6, "ultrasonic thickness gauge calibration frequency", ["15_calibration_procedure_ut_gauge"]),
    (7, "hot work permit requirements near tank farm", ["07_hot_work_permit_policy"]),
    (8, "corrosion under insulation inspection interval", ["05_corrosion_under_insulation_guideline"]),
    (9, "radiography acceptance criteria for pipe welds", ["16_ndt_radiography_procedure"]),
    (10, "FCC catalyst performance and pricing", ["12_vendor_letter_fcc_catalyst", "26_vendor_negotiation_budget_letter"]),
    (11, "heat exchanger tube plugging criteria", ["32_heat_exchanger_tube_bundle_procedure", "20_audit_history_heat_exchanger"]),
    (12, "sulphur recovery unit efficiency", ["34_sulphur_recovery_unit_operating_note"]),
    (13, "confidential capacity expansion assessment", ["27_confidential_strategy_memo_capacity_expansion"]),
    (14, "example approval note format for return to service", ["25_approval_note_example_past"]),
]

DECOYS = {
    "36_decoy_hr_leave_policy",
    "37_decoy_it_password_policy",
    "38_decoy_travel_policy",
    "39_decoy_cafeteria_facilities_notice",
    "40_decoy_marketing_brochure",
}


@pytest.mark.parametrize("q_num, query, expected_docs", CALIBRATION_QUERIES)
def test_calibration_query(q_num, query, expected_docs):
    settings = get_settings()
    kb = KnowledgeBase(settings)
    collection = kb._ensure()

    res = collection.query(
        query_embeddings=kb._embed([query]),
        n_results=5,
        include=["documents", "metadatas", "distances"],
    )
    docs = res["metadatas"][0]
    dists = res["distances"][0]

    top3_ids = [d["chunk_id"].split("#")[0] for d in docs[:3]]

    # 1. Expected document must appear in top 3
    has_expected = any(any(e in doc_id for e in expected_docs) for doc_id in top3_ids)
    assert has_expected, f"Query {q_num} ('{query}') did not find any of {expected_docs} in top 3: {top3_ids}"

    # 2. No decoy document in top 3
    has_decoy = any(any(decoy in doc_id for decoy in DECOYS) for doc_id in top3_ids)
    assert not has_decoy, f"Query {q_num} surfaced a decoy in top 3: {top3_ids}"
