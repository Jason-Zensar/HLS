"""Knowledge-graph schema: node labels, permitted relationship types and their endpoint types.

Every node carries the base label `KG` plus its type label(s); `id` is unique across the graph.
Relationship categories:
  clinical     - protocol-derived assertions, must carry provenance (claim_id, chunk, page, quote)
  structural   - document structure / identity (Document, sections, chunks, versions)
  terminology  - reference terminology (drug class membership); NOT protocol evidence
  mention      - a document mentions an entity; no clinical meaning
Schema extensions beyond the base specification are marked EXT with the reason.
"""
from __future__ import annotations

NODE_TYPES = {
    # clinical study entities
    "ClinicalTrial", "Protocol", "StudyArm", "StudyCohort", "StudyPopulation", "StudyPhase", "StudyDesign", "Sponsor",
    # medical entities
    "Disease", "CancerSubtype", "Drug", "DrugClass", "Intervention", "CombinationTherapy", "Biomarker", "Gene", "Protein",
    "MolecularTarget", "Symptom", "ClinicalCondition", "AdverseEvent",
    # protocol entities
    "EligibilityCriterion", "InclusionCriterion", "ExclusionCriterion", "DoseSpecification", "RouteOfAdministration",
    "TreatmentCycle", "Assessment", "DiagnosticProcedure", "LaboratoryTest", "Endpoint", "StatisticalMethod",
    "FollowUpProcedure", "SafetyMonitoringRule",
    # EXT: treatment setting (neoadjuvant / adjuvant / metastatic / line of therapy) is a core axis
    # of breast-cancer protocol comparison and is not covered by StudyPopulation.
    "TreatmentSetting",
    # evidence & provenance
    "Document", "DocumentSection", "EvidenceChunk", "Table", "ExtractedClaim",
}

INTERVENTIONS = {"Drug", "Intervention", "CombinationTherapy"}
CONDITIONS = {"Disease", "CancerSubtype", "TreatmentSetting", "StudyPopulation", "AdverseEvent", "ClinicalCondition"}
ASSESSMENTS = {"Assessment", "LaboratoryTest", "DiagnosticProcedure"}
CRITERIA = {"InclusionCriterion", "ExclusionCriterion", "EligibilityCriterion"}

# predicate -> (allowed subject types, allowed object types, category, description)
RELATIONSHIPS: dict[str, tuple[set[str], set[str], str, str]] = {
    "INVESTIGATES": ({"Protocol"}, INTERVENTIONS, "clinical", "Protocol studies this intervention as a study treatment"),
    "STUDIES": ({"Protocol"}, {"Disease", "CancerSubtype"}, "clinical", "Protocol's target disease / subtype"),
    "HAS_PHASE": ({"Protocol"}, {"StudyPhase"}, "clinical", "Development phase stated in the protocol"),
    "HAS_DESIGN": ({"Protocol"}, {"StudyDesign"}, "clinical", "Design feature stated in the protocol"),
    "HAS_SETTING": ({"Protocol"}, {"TreatmentSetting"}, "clinical", "EXT: treatment setting / line of therapy"),
    "HAS_POPULATION": ({"Protocol"}, {"StudyPopulation"}, "clinical", "Population characteristic stated in the protocol"),
    "INCLUDES_ARM": ({"Protocol"}, {"StudyArm"}, "clinical", "Protocol defines this arm / cohort"),
    "USES_INTERVENTION": ({"StudyArm"}, INTERVENTIONS, "clinical", "Arm description names this intervention"),
    "COMBINED_WITH": (INTERVENTIONS, INTERVENTIONS, "clinical", "Explicit combination statement in a protocol"),
    "COMPARED_WITH": (INTERVENTIONS, INTERVENTIONS, "clinical", "EXT: explicit 'versus' comparison in a protocol"),
    "FOLLOWED_BY": (INTERVENTIONS, INTERVENTIONS, "clinical", "EXT: sequential regimen ('A followed by B')"),
    "HAS_DOSE_SPECIFICATION": ({"Protocol"}, {"DoseSpecification"}, "clinical", "Protocol-specific dose statement"),
    "DOSE_OF": ({"DoseSpecification"}, {"Drug"}, "clinical", "EXT: links a protocol-specific dose to its drug"),
    "ADMINISTERED_VIA": ({"DoseSpecification"}, {"RouteOfAdministration"}, "clinical", "Route in the dose statement"),
    "HAS_TREATMENT_CYCLE": ({"Protocol"}, {"TreatmentCycle"}, "clinical", "Cycle length stated in the protocol"),
    "HAS_INCLUSION_CRITERION": ({"Protocol"}, {"InclusionCriterion"}, "clinical", "Inclusion criterion"),
    "HAS_EXCLUSION_CRITERION": ({"Protocol"}, {"ExclusionCriterion"}, "clinical", "Exclusion criterion"),
    "ASSOCIATED_WITH_BIOMARKER": ({"Protocol"} | CRITERIA, {"Biomarker"}, "clinical", "Biomarker used by the protocol / criterion"),
    "REFERENCES_CONDITION": (CRITERIA, CONDITIONS, "clinical", "EXT: condition named inside an eligibility criterion"),
    "REFERENCES_DRUG": (CRITERIA, INTERVENTIONS, "clinical", "EXT: prior / prohibited therapy named in a criterion"),
    "HAS_PRIMARY_ENDPOINT": ({"Protocol"}, {"Endpoint"}, "clinical", "Primary endpoint"),
    "HAS_SECONDARY_ENDPOINT": ({"Protocol"}, {"Endpoint"}, "clinical", "Secondary endpoint"),
    "HAS_EXPLORATORY_ENDPOINT": ({"Protocol"}, {"Endpoint"}, "clinical", "EXT: exploratory endpoint"),
    "MEASURES_ENDPOINT": ({"Protocol"}, {"Endpoint"}, "clinical", "Endpoint whose level is not stated"),
    "MONITORS_ADVERSE_EVENT": ({"Protocol", "SafetyMonitoringRule"}, {"AdverseEvent"}, "clinical", "Adverse event monitored / described in safety sections"),
    "ASSOCIATED_ADVERSE_EVENT": ({"Drug"}, {"AdverseEvent"}, "clinical", "EXT: protocol sentence reporting this AE for this drug (not causal)"),
    "HAS_SAFETY_RULE": ({"Protocol"}, {"SafetyMonitoringRule"}, "clinical", "Dose hold / discontinuation rule"),
    "REQUIRES_ASSESSMENT": ({"Protocol"} | CRITERIA, ASSESSMENTS, "clinical", "Assessment required by the protocol"),
    "USES_STATISTICAL_METHOD": ({"Protocol"}, {"StatisticalMethod"}, "clinical", "EXT: statistical method in the analysis plan"),
    "HAS_FOLLOW_UP": ({"Protocol"}, {"FollowUpProcedure"}, "clinical", "Follow-up schedule statement"),
    "TARGETS": ({"Drug"}, {"MolecularTarget"}, "clinical", "Mechanism stated in a protocol sentence"),
    # structural
    "DESCRIBED_IN": ({"Protocol"}, {"Document"}, "structural", "Protocol content comes from this document"),
    "VERSION_OF": ({"Protocol"}, {"ClinicalTrial"}, "structural", "Protocol document is a version for this registered trial"),
    "AMENDS": ({"Protocol"}, {"Protocol"}, "structural", "Later protocol version amends an earlier one (explicit version info)"),
    "SPONSORED_BY": ({"Protocol"}, {"Sponsor"}, "structural", "Sponsor named in the protocol"),
    "PART_OF": ({"DocumentSection", "EvidenceChunk", "Table"}, {"Document", "DocumentSection"}, "structural", "Document hierarchy"),
    "DERIVED_FROM": ({"EvidenceChunk", "ExtractedClaim"}, {"Table", "Document"}, "structural", "Provenance"),
    "SUPPORTED_BY": ({"ExtractedClaim"}, {"EvidenceChunk"}, "structural", "Claim is supported by this passage"),
    # terminology
    "BELONGS_TO_CLASS": ({"Drug"}, {"DrugClass"}, "terminology", "Reference drug classification (not from protocols)"),
    "SUBCLASS_OF": ({"DrugClass"}, {"DrugClass"}, "terminology", "Reference class hierarchy"),
    "CONTAINS_DRUG": ({"CombinationTherapy"}, {"Drug"}, "terminology", "Regimen abbreviation components"),
    # mention
    "MENTIONS": ({"Document"}, NODE_TYPES, "mention", "Document text mentions the entity (no clinical meaning)"),
}

CLINICAL = {k for k, v in RELATIONSHIPS.items() if v[2] == "clinical"}
EXPLORABLE = {k for k, v in RELATIONSHIPS.items() if v[2] in ("clinical", "structural", "terminology") and k not in ("PART_OF", "SUPPORTED_BY", "DERIVED_FROM")}

# Visual / semantic grouping used by the UI legend
NODE_GROUP = {
    "ClinicalTrial": "trial", "Protocol": "trial", "StudyArm": "trial", "StudyCohort": "trial", "StudyPhase": "trial",
    "StudyDesign": "trial", "Sponsor": "trial", "StudyPopulation": "condition", "TreatmentSetting": "condition",
    "Drug": "intervention", "DrugClass": "intervention", "Intervention": "intervention", "CombinationTherapy": "intervention",
    "DoseSpecification": "intervention", "RouteOfAdministration": "intervention", "TreatmentCycle": "intervention",
    "Disease": "condition", "CancerSubtype": "condition", "ClinicalCondition": "condition",
    "Biomarker": "biomarker", "Gene": "biomarker", "Protein": "biomarker", "MolecularTarget": "biomarker",
    "InclusionCriterion": "criterion", "ExclusionCriterion": "criterion", "EligibilityCriterion": "criterion",
    "Endpoint": "outcome", "StatisticalMethod": "outcome", "Assessment": "outcome", "LaboratoryTest": "outcome",
    "DiagnosticProcedure": "outcome", "FollowUpProcedure": "outcome",
    "AdverseEvent": "safety", "Symptom": "safety", "SafetyMonitoringRule": "safety",
    "Document": "evidence", "DocumentSection": "evidence", "EvidenceChunk": "evidence", "Table": "evidence",
    "ExtractedClaim": "evidence",
}


def primary_type(labels: list[str]) -> str:
    """Pick the most specific schema type from a node's labels."""
    pref = [l for l in labels if l not in ("KG", "EligibilityCriterion", "Symptom", "Gene", "Protein")]
    for l in pref:
        if l in NODE_TYPES:
            return l
    for l in labels:
        if l in NODE_TYPES:
            return l
    return labels[0] if labels else "Unknown"


def validate_edge(pred: str, s_type: str, o_type: str) -> str | None:
    """Return None when valid, otherwise a rejection reason (Layer-3 relationship validation)."""
    spec = RELATIONSHIPS.get(pred)
    if not spec:
        return f"relationship type {pred} is not in the schema"
    if s_type not in spec[0]:
        return f"{pred}: subject type {s_type} not permitted"
    if o_type not in spec[1]:
        return f"{pred}: object type {o_type} not permitted"
    return None
