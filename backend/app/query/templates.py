"""Allowlisted, parameterised, read-only Cypher templates.

Natural-language and structured queries can only execute these patterns. Each template returns
rows with a single column `paths` (a list of graph paths), so retrieval results are always real
stored nodes and relationships. User text never becomes Cypher; it only fills $parameters.
Background-literature combination statements are excluded from clinical answers by default.
"""
from __future__ import annotations

CLINICAL_OK = "coalesce(r.assertion_type,'') <> 'background_statement'"

TEMPLATES: dict[str, dict] = {
    "trials_for_intervention": {
        "description": "Protocols that investigate an intervention (and the arms that use it)",
        "params": ["id"],
        "cypher": """
            MATCH (x:KG {id: $id})
            MATCH p1 = (pr:Protocol)-[r:INVESTIGATES]->(x)
            OPTIONAL MATCH p2 = (pr)-[:INCLUDES_ARM]->(:StudyArm)-[:USES_INTERVENTION]->(x)
            OPTIONAL MATCH p3 = (pr)-[:VERSION_OF]->(:ClinicalTrial)
            WITH pr, p1, collect(DISTINCT p2)[..3] AS arms, collect(DISTINCT p3)[..1] AS tr, max(r.extraction_confidence) AS c
            ORDER BY c DESC LIMIT $limit
            RETURN [p1] + arms + tr AS paths""",
    },
    "trials_for_class": {
        "description": "Protocols investigating any drug of a drug class (class membership is reference terminology)",
        "params": ["id"],
        "cypher": """
            MATCH (c:DrugClass {id: $id})
            MATCH p1 = (pr:Protocol)-[r:INVESTIGATES]->(d:Drug)-[:BELONGS_TO_CLASS]->(:DrugClass)-[:SUBCLASS_OF*0..2]->(c)
            WITH pr, d, p1, r ORDER BY r.extraction_confidence DESC LIMIT $limit
            RETURN [p1] AS paths""",
    },
    "trials_for_condition": {
        "description": "Protocols that study a disease / subtype, or have a setting / population",
        "params": ["id"],
        "cypher": """
            MATCH (x:KG {id: $id})
            MATCH p1 = (pr:Protocol)-[r:STUDIES|HAS_SETTING|HAS_POPULATION]->(x)
            OPTIONAL MATCH p2 = (pr)-[:INVESTIGATES]->(:Drug)
            WITH pr, p1, r, collect(DISTINCT p2)[..4] AS drugs ORDER BY r.extraction_confidence DESC LIMIT $limit
            RETURN [p1] + drugs AS paths""",
    },
    "trials_for_biomarker": {
        "description": "Protocols associated with a biomarker, directly or through eligibility criteria",
        "params": ["id"],
        "cypher": """
            MATCH (b:KG {id: $id})
            CALL (b) {
              MATCH p = (pr:Protocol)-[r:ASSOCIATED_WITH_BIOMARKER]->(b) RETURN pr, p, r.extraction_confidence AS c
              UNION
              MATCH p = (pr:Protocol)-[:HAS_INCLUSION_CRITERION|HAS_EXCLUSION_CRITERION]->(:EligibilityCriterion)-[r:ASSOCIATED_WITH_BIOMARKER]->(b)
              RETURN pr, p, r.extraction_confidence AS c
            }
            WITH pr, collect(p)[..3] AS ps, max(c) AS c ORDER BY c DESC LIMIT $limit
            RETURN ps AS paths""",
    },
    "trials_for_endpoint": {
        "description": "Protocols measuring an endpoint (with its stated level)",
        "params": ["id"],
        "cypher": """
            MATCH (e:Endpoint {id: $id})
            MATCH p = (pr:Protocol)-[r:HAS_PRIMARY_ENDPOINT|HAS_SECONDARY_ENDPOINT|HAS_EXPLORATORY_ENDPOINT|MEASURES_ENDPOINT]->(e)
            WITH pr, collect(p) AS ps, max(r.extraction_confidence) AS c ORDER BY c DESC LIMIT $limit
            RETURN ps AS paths""",
    },
    "trials_for_adverse_event": {
        "description": "Protocols that monitor an adverse event, plus drug-level protocol statements",
        "params": ["id"],
        "cypher": """
            MATCH (ae:AdverseEvent {id: $id})
            CALL (ae) {
              MATCH p = (pr:Protocol)-[r:MONITORS_ADVERSE_EVENT]->(ae) RETURN pr, p, r.extraction_confidence AS c
              UNION
              MATCH p = (pr:Protocol)-[:INVESTIGATES]->(d:Drug)-[r:ASSOCIATED_ADVERSE_EVENT]->(ae) WHERE r.protocol_id = pr.id
              RETURN pr, p, r.extraction_confidence AS c
            }
            WITH pr, collect(p)[..3] AS ps, max(c) AS c ORDER BY c DESC LIMIT $limit
            RETURN ps AS paths""",
    },
    "trials_for_entity_generic": {
        "description": "Protocols with any clinical relationship to the entity",
        "params": ["id"],
        "cypher": """
            MATCH (x:KG {id: $id})
            MATCH p = (pr:Protocol)-[r]->(x) WHERE r.claim_id IS NOT NULL
            WITH pr, collect(p)[..3] AS ps, max(r.extraction_confidence) AS c ORDER BY c DESC LIMIT $limit
            RETURN ps AS paths""",
    },
    "combination": {
        "description": "Protocols where intervention A is explicitly combined with B (B may be a drug class)",
        "params": ["a", "b"],
        "cypher": """
            MATCH (a:KG {id: $a}), (b0:KG {id: $b})
            CALL (a, b0) {
              MATCH p = (pr:Protocol)-[:INVESTIGATES]->(a)-[r:COMBINED_WITH|FOLLOWED_BY]-(b)
              WHERE r.protocol_id = pr.id AND """ + CLINICAL_OK + """
                AND (b = b0 OR EXISTS { MATCH (b)-[:BELONGS_TO_CLASS]->(:DrugClass)-[:SUBCLASS_OF*0..2]->(b0) })
              OPTIONAL MATCH pc = (b)-[:BELONGS_TO_CLASS]->(:DrugClass)-[:SUBCLASS_OF*0..2]->(b0)
              RETURN pr, [p] + CASE WHEN pc IS NULL THEN [] ELSE [pc] END AS ps
              UNION
              MATCH p = (pr:Protocol)-[:INCLUDES_ARM]->(arm:StudyArm)-[:USES_INTERVENTION]->(a), q = (arm)-[:USES_INTERVENTION]->(b)
              WHERE b <> a AND (b = b0 OR EXISTS { MATCH (b)-[:BELONGS_TO_CLASS]->(:DrugClass)-[:SUBCLASS_OF*0..2]->(b0) })
              OPTIONAL MATCH pc = (b)-[:BELONGS_TO_CLASS]->(:DrugClass)-[:SUBCLASS_OF*0..2]->(b0)
              RETURN pr, [p, q] + CASE WHEN pc IS NULL THEN [] ELSE [pc] END AS ps
            }
            WITH pr, collect(ps) AS pss LIMIT $limit
            RETURN reduce(acc = [], x IN pss | acc + x) AS paths""",
    },
    "eligibility_for_intervention": {
        "description": "Inclusion / exclusion criteria of protocols investigating an intervention",
        "params": ["id"],
        "cypher": """
            MATCH (x:KG {id: $id})<-[:INVESTIGATES]-(pr:Protocol)
            WITH DISTINCT pr, x LIMIT $limit
            MATCH p0 = (pr)-[:INVESTIGATES]->(x)
            OPTIONAL MATCH p = (pr)-[:HAS_INCLUSION_CRITERION|HAS_EXCLUSION_CRITERION]->(c:EligibilityCriterion)
            WITH pr, p0, collect(p)[..$per] AS cs
            RETURN [p0] + cs AS paths""",
    },
    "eligibility_of_protocol": {
        "description": "Inclusion / exclusion criteria of one protocol",
        "params": ["id"],
        "cypher": """
            MATCH (pr:Protocol {id: $id})
            OPTIONAL MATCH p = (pr)-[:HAS_INCLUSION_CRITERION|HAS_EXCLUSION_CRITERION]->(c:EligibilityCriterion)
            OPTIONAL MATCH q = (c)-[:ASSOCIATED_WITH_BIOMARKER|REFERENCES_CONDITION|REFERENCES_DRUG]->()
            WITH pr, collect(DISTINCT p)[..80] AS ps, collect(DISTINCT q)[..120] AS qs
            RETURN ps + qs AS paths""",
    },
    "biomarker_eligibility": {
        "description": "Protocols whose eligibility criteria use a biomarker",
        "params": ["id"],
        "cypher": """
            MATCH p = (pr:Protocol)-[rc:HAS_INCLUSION_CRITERION|HAS_EXCLUSION_CRITERION]->(c:EligibilityCriterion)-[r:ASSOCIATED_WITH_BIOMARKER]->(b:KG {id: $id})
            WITH pr, collect(p)[..$per] AS ps, max(r.extraction_confidence) AS conf ORDER BY conf DESC LIMIT $limit
            RETURN ps AS paths""",
    },
    "dosing_for_drug": {
        "description": "Protocol-specific dose specifications of a drug",
        "params": ["id"],
        "cypher": """
            MATCH p = (pr:Protocol)-[:HAS_DOSE_SPECIFICATION]->(ds:DoseSpecification)-[:DOSE_OF]->(d:KG {id: $id})
            OPTIONAL MATCH q = (ds)-[:ADMINISTERED_VIA]->(:RouteOfAdministration)
            OPTIONAL MATCH cy = (pr)-[:HAS_TREATMENT_CYCLE]->(:TreatmentCycle)
            WITH pr, collect(DISTINCT p)[..$per] AS ps, collect(DISTINCT q)[..$per] AS qs, collect(DISTINCT cy)[..1] AS cys LIMIT $limit
            RETURN ps + qs + cys AS paths""",
    },
    "drug_adverse_events": {
        "description": "Adverse events stated for a drug in protocols, and AEs monitored by protocols investigating it",
        "params": ["id"],
        "cypher": """
            MATCH (d:KG {id: $id})
            MATCH p = (pr:Protocol)-[:INVESTIGATES]->(d)-[r:ASSOCIATED_ADVERSE_EVENT]->(ae:AdverseEvent)
            WHERE r.protocol_id = pr.id AND ($ae IS NULL OR ae.id = $ae)
            WITH pr, collect(p)[..$per] AS ps LIMIT $limit
            RETURN ps AS paths""",
    },
    "drug_ae_monitoring": {
        "description": "Protocols investigating a drug that monitor a given adverse event",
        "params": ["id", "ae"],
        "cypher": """
            MATCH p = (ae:AdverseEvent {id: $ae})<-[:MONITORS_ADVERSE_EVENT]-(pr:Protocol)-[:INVESTIGATES]->(d:KG {id: $id})
            WITH pr, collect(p)[..2] AS ps LIMIT $limit
            RETURN ps AS paths""",
    },
    "mention_context": {
        "description": "Documents that mention an entity (mention only - no clinical relationship implied)",
        "params": ["id"],
        "cypher": """
            MATCH p = (pr:Protocol)-[:DESCRIBED_IN]->(doc:Document)-[m:MENTIONS]->(x:KG {id: $id})
            WITH pr, p, m ORDER BY m.count DESC LIMIT $limit
            RETURN [p] AS paths""",
    },
    "same_intervention_diff_primary_endpoints": {
        "description": "Protocols sharing an intervention but stating different primary endpoints",
        "params": [],
        "cypher": """
            MATCH (p1:Protocol)-[:INVESTIGATES]->(d:Drug)<-[:INVESTIGATES]-(p2:Protocol)
            WHERE p1.id < p2.id AND ($id IS NULL OR d.id = $id)
            MATCH (p1)-[:HAS_PRIMARY_ENDPOINT]->(e1:Endpoint), (p2)-[:HAS_PRIMARY_ENDPOINT]->(e2:Endpoint)
            WHERE e1 <> e2 AND NOT (p2)-[:HAS_PRIMARY_ENDPOINT]->(e1) AND NOT (p1)-[:HAS_PRIMARY_ENDPOINT]->(e2)
            WITH d, p1, p2, e1, e2 LIMIT $limit
            MATCH a = (p1)-[:INVESTIGATES]->(d)<-[:INVESTIGATES]-(p2)
            MATCH b = (p1)-[:HAS_PRIMARY_ENDPOINT]->(e1)
            MATCH c = (p2)-[:HAS_PRIMARY_ENDPOINT]->(e2)
            RETURN [a, b, c] AS paths""",
    },
    "shared_with_protocol": {
        "description": "Protocols sharing drugs / biomarkers / primary endpoints / subtypes with a protocol",
        "params": ["id"],
        "cypher": """
            MATCH (p0:Protocol {id: $id})-[r0]->(x)
            WHERE type(r0) IN $rels AND NOT x:EligibilityCriterion AND NOT x:DoseSpecification
            MATCH (p2:Protocol)-[r2]->(x) WHERE p2 <> p0 AND type(r2) = type(r0)
            WITH p0, p2, collect(DISTINCT x) AS shared ORDER BY size(shared) DESC LIMIT $limit
            UNWIND shared[..6] AS x
            MATCH a = (p0)-[r0]->(x)<-[r2]-(p2) WHERE type(r0) IN $rels AND type(r2) = type(r0)
            RETURN collect(a)[..6] AS paths""",
    },
    "shared_entities_global": {
        "description": "Entities shared by the most protocols for a relationship type",
        "params": ["rel"],
        "cypher": """
            MATCH (pr:Protocol)-[r]->(x) WHERE type(r) = $rel AND r.claim_id IS NOT NULL
            WITH x, collect(DISTINCT pr) AS prs WHERE size(prs) >= 2
            WITH x, prs ORDER BY size(prs) DESC LIMIT $per
            UNWIND prs[..12] AS pr
            MATCH p = (pr)-[r]->(x) WHERE type(r) = $rel
            RETURN collect(p) AS paths""",
    },
    "trace_intervention": {
        "description": "Drug -> arm -> protocol -> population / subtype / primary endpoint (multi-hop trace)",
        "params": ["id"],
        "cypher": """
            MATCH (d:KG {id: $id})<-[:INVESTIGATES]-(pr:Protocol)
            WITH d, pr LIMIT $limit
            OPTIONAL MATCH a = (d)<-[:USES_INTERVENTION]-(:StudyArm)<-[:INCLUDES_ARM]-(pr)
            OPTIONAL MATCH b = (pr)-[:HAS_POPULATION|STUDIES|HAS_SETTING]->()
            OPTIONAL MATCH c = (pr)-[:HAS_PRIMARY_ENDPOINT]->(:Endpoint)
            OPTIONAL MATCH t = (pr)-[:DESCRIBED_IN]->(:Document)
            OPTIONAL MATCH i = (pr)-[:INVESTIGATES]->(d)
            RETURN [x IN collect(DISTINCT a)[..2] + collect(DISTINCT b)[..4] + collect(DISTINCT c)[..3] + collect(DISTINCT t)[..1] + collect(DISTINCT i)[..1] WHERE x IS NOT NULL] AS paths""",
    },
    "similar_protocols": {
        "description": "Protocols most similar by treatments, subtypes, biomarkers, endpoints, settings (Jaccard)",
        "params": ["id"],
        "cypher": """
            MATCH (p0:Protocol {id: $id})-[r0]->(x) WHERE type(r0) IN $rels
            WITH p0, collect(DISTINCT x) AS xs
            MATCH (p2:Protocol)-[r2]->(y) WHERE p2 <> p0 AND type(r2) IN $rels
            WITH p0, xs, p2, collect(DISTINCT y) AS ys
            WITH p0, xs, p2, ys, [y IN ys WHERE y IN xs] AS shared
            WHERE size(shared) > 0
            WITH p0, p2, shared, toFloat(size(shared)) / (size(xs) + size(ys) - size(shared)) AS jaccard
            ORDER BY jaccard DESC LIMIT $limit
            UNWIND shared[..6] AS s
            MATCH a = (p0)-[r0]->(s)<-[r2]-(p2) WHERE type(r0) IN $rels AND type(r2) IN $rels
            RETURN collect(a)[..6] AS paths, p2.id AS pid, jaccard""",
    },
    "path_between": {
        "description": "Shortest relationship paths between two entities (clinical / structural edges only)",
        "params": ["a", "b"],
        "cypher": """
            MATCH (a:KG {id: $a}), (b:KG {id: $b})
            MATCH p = allShortestPaths((a)-[*..5]-(b))
            WHERE all(r IN relationships(p) WHERE type(r) IN $rels AND coalesce(r.assertion_type,'') <> 'background_statement')
              AND all(n IN nodes(p) WHERE NOT n:ExtractedClaim AND NOT n:EvidenceChunk AND NOT n:DocumentSection)
            WITH p LIMIT $limit
            RETURN [p] AS paths""",
    },
    "protocol_overview": {
        "description": "Clinical relationships of one protocol",
        "params": ["id"],
        "cypher": """
            MATCH (pr:Protocol {id: $id})
            OPTIONAL MATCH p = (pr)-[r]->(x)
            WHERE type(r) IN $rels
            WITH pr, p, r ORDER BY r.extraction_confidence DESC
            WITH pr, collect(p)[..$per] AS ps
            OPTIONAL MATCH arm = (pr)-[:INCLUDES_ARM]->(:StudyArm)-[:USES_INTERVENTION]->()
            OPTIONAL MATCH v = (pr)-[:VERSION_OF]->(:ClinicalTrial)<-[:VERSION_OF]-(:Protocol)
            RETURN ps + collect(DISTINCT arm)[..12] + collect(DISTINCT v)[..6] AS paths""",
    },
    "entity_neighborhood": {
        "description": "Direct clinical / structural neighbourhood of an entity",
        "params": ["id"],
        "cypher": """
            MATCH (x:KG {id: $id})
            MATCH p = (x)-[r]-(y)
            WHERE type(r) IN $rels AND NOT y:ExtractedClaim AND NOT y:EvidenceChunk
            WITH p, r ORDER BY coalesce(r.extraction_confidence, 0.5) DESC LIMIT $per
            RETURN collect(p) AS paths""",
    },
    "top_entities": {
        "description": "Most frequently investigated / studied entities of a type",
        "params": ["rel", "label"],
        "cypher": """
            MATCH (pr:Protocol)-[r]->(x) WHERE type(r) = $rel AND $label IN labels(x)
            WITH x, count(DISTINCT pr) AS n ORDER BY n DESC LIMIT $per
            MATCH p = (pr:Protocol)-[r]->(x) WHERE type(r) = $rel
            WITH x, n, collect(p)[..6] AS ps
            RETURN ps AS paths""",
    },
}


def get(name: str) -> dict:
    if name not in TEMPLATES:
        raise KeyError(f"template '{name}' is not allowlisted")
    return TEMPLATES[name]
