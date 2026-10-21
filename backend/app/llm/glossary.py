"""Plain-language glossary of terms that appear in breast-cancer trial protocols.

Used deterministically (no AI needed) to explain the terms found in a protocol, and given to the model as a reference.
Each entry: (term shown, regex that finds it, explanation for a non-medical reader).
"""
from __future__ import annotations

import re

_G: list[tuple[str, str, str]] = [
    # study basics
    ("Protocol", r"\bprotocol\b", "The official plan of a clinical study: why it is done, who can join, what treatment is given and how results are measured."),
    ("Clinical trial", r"\bclinical (trial|study)\b", "A research study in people that tests whether a medical treatment is safe and how well it works."),
    ("Phase 1", r"\bphase (1|i)\b(?![/ab])", "An early study in a small group to find a safe dose and learn about side effects."),
    ("Phase 2", r"\bphase (2|ii)\b(?![/ab])", "A study that checks whether a treatment shows signs of working and continues to check safety."),
    ("Phase 3", r"\bphase (3|iii)\b(?![/ab])", "A large study that compares a new treatment with the current standard treatment."),
    ("Randomized", r"\brandomi[sz](ed|ation)\b", "Participants are assigned to groups by chance (like a coin toss) so the groups can be compared fairly."),
    ("Open-label", r"\bopen[- ]label\b", "Both the participants and the doctors know which treatment is being given."),
    ("Double-blind", r"\bdouble[- ]blind(ed)?\b", "Neither the participants nor the doctors know who receives which treatment, to avoid bias."),
    ("Placebo", r"\bplacebos?\b", "A dummy treatment with no active medicine, used for comparison."),
    ("Arm", r"\b(treatment|study) arms?\b|\barm [a-d]\b", "A group of participants who all receive the same treatment plan."),
    ("Cohort", r"\bcohorts?\b", "A group of participants with something in common, followed during the study."),
    ("Sponsor", r"\bsponsor\b", "The company or institution that runs and pays for the study."),
    ("Informed consent", r"\binformed consent\b", "The process of explaining the study to a person and getting their written agreement before they join."),
    ("Statistical analysis plan (SAP)", r"\bstatistical analysis plan\b|\bSAP\b", "A document describing exactly how the study results will be analysed."),
    ("Amendment", r"\bamendments?\b", "An official change made to the protocol after the study has started."),
    ("Inclusion criteria", r"\binclusion criteria\b", "Conditions a person must meet to be allowed to join the study."),
    ("Exclusion criteria", r"\bexclusion criteria\b", "Conditions that prevent a person from joining the study, usually for safety reasons."),
    ("Stratification", r"\bstratifi(ed|cation)\b", "Balancing the study groups on important factors (for example hormone status) so the comparison is fair."),
    ("Cycle", r"\b\d+[- ]day cycles?\b|\btreatment cycles?\b", "A repeating period of treatment (for example 21 days) that may include rest days."),
    ("Intravenous (IV)", r"\bintravenous(ly)?\b|\bIV\b", "Given directly into a vein through a drip or injection."),
    ("Oral", r"\borally\b|\boral\b", "Taken by mouth, for example as a tablet."),
    ("Subcutaneous", r"\bsubcutaneous(ly)?\b", "Injected just under the skin."),
    ("mg/m2", r"mg/m2|mg/m²", "A dose calculated from body size (body surface area), common for chemotherapy."),
    ("Dose modification", r"\bdose (modification|reduction|interruption)s?\b", "Lowering, pausing or stopping a dose, usually because of side effects."),
    # disease
    ("Breast cancer subtypes", r"\bsubtypes?\b", "Breast cancers are grouped by markers on the cancer cells (hormone receptors and HER2); each group is treated differently."),
    ("HER2", r"\bHER2\b|\bERBB2\b", "A protein on some cancer cells that makes them grow faster. HER2-positive cancers can be treated with HER2-targeted drugs."),
    ("HER2-low", r"\bHER2[- ]low\b", "Cancers with a small amount of HER2; some newer drugs (such as trastuzumab deruxtecan) can work in them."),
    ("Hormone receptor (HR)", r"\bhormone receptors?\b|\bHR[+-]|\bHR[- ]positive\b", "Receptors for oestrogen or progesterone. HR-positive cancers often grow in response to hormones and can be treated with hormone therapy."),
    ("Estrogen receptor (ER)", r"\bestrogen receptor\b|\boestrogen receptor\b|\bER[+-]|\bER[- ]positive\b", "A receptor for the hormone oestrogen. ER-positive cancers usually respond to hormone (endocrine) therapy."),
    ("Progesterone receptor (PR)", r"\bprogesterone receptor\b|\bPgR\b", "A receptor for the hormone progesterone, tested together with the oestrogen receptor."),
    ("Triple-negative breast cancer (TNBC)", r"\btriple[- ]negative\b|\bTNBC\b", "Breast cancer without oestrogen receptors, progesterone receptors or HER2, so hormone and HER2 drugs do not work; chemotherapy and immunotherapy are used."),
    ("Metastatic", r"\bmetasta(tic|ses|sis)\b", "Cancer that has spread from the breast to other parts of the body."),
    ("Locally advanced", r"\blocally advanced\b", "Cancer that has grown into nearby tissue or lymph nodes but not to distant organs."),
    ("Early breast cancer", r"\bearly(-stage)? breast cancer\b|\bearly BC\b", "Cancer that is confined to the breast and nearby lymph nodes and can usually be removed by surgery."),
    ("Neoadjuvant", r"\bneo-?adjuvant\b", "Treatment given before surgery, usually to shrink the tumour."),
    ("Adjuvant", r"(?<!neo)(?<!neo-)\badjuvant\b", "Treatment given after surgery to lower the chance of the cancer coming back."),
    ("First-line", r"\bfirst[- ]line\b|\b1L\b", "The first treatment given for a stage of the disease, usually after diagnosis of advanced cancer."),
    ("Brain metastases", r"\bbrain metasta", "Cancer that has spread to the brain."),
    ("ECOG performance status", r"\bECOG\b", "A 0 to 5 score of how well a person can carry out daily activities; 0 means fully active, higher numbers mean more limited."),
    ("BRCA mutation", r"\bg?BRCA[12]?\b", "An inherited change in the BRCA1 or BRCA2 gene that raises cancer risk; such cancers may respond to PARP inhibitors."),
    ("PIK3CA mutation", r"\bPIK3CA\b", "A change in a gene that drives some hormone-positive cancers; drugs such as alpelisib target it."),
    ("ESR1 mutation", r"\bESR1\b", "A change in the oestrogen receptor gene that can make hormone therapy stop working."),
    ("PD-L1", r"\bPD-?L1\b", "A protein that helps cancers hide from the immune system; its level can predict benefit from immunotherapy."),
    ("Ki-67", r"\bKi-?67\b", "A marker of how fast cancer cells are dividing."),
    ("ctDNA", r"\bct-?DNA\b|\bcirculating tumou?r DNA\b", "Tiny fragments of tumour DNA in the blood, measured with a blood test."),
    ("Tumour-infiltrating lymphocytes (TILs)", r"\bTILs?\b|\btumou?r[- ]infiltrating lymphocytes\b", "Immune cells found inside a tumour; more TILs can mean a better immune response."),
    ("Biomarker", r"\bbiomarkers?\b", "A measurable sign in tissue or blood (such as HER2 or PD-L1) that helps choose or judge a treatment."),
    # treatments
    ("Chemotherapy", r"\bchemotherap(y|ies)\b", "Medicines that kill fast-growing cells, including cancer cells."),
    ("Immunotherapy", r"\bimmunotherap(y|ies)\b|\bimmune checkpoint\b", "Treatment that helps the body's own immune system attack cancer."),
    ("Endocrine (hormone) therapy", r"\bendocrine therapy\b|\bhormon(e|al) therapy\b", "Medicines that block oestrogen or lower its level, used for hormone-receptor-positive cancer."),
    ("Aromatase inhibitor (AI)", r"\baromatase inhibitors?\b|\bNSAI\b|\bletrozole\b|\banastrozole\b|\bexemestane\b", "Hormone tablets (letrozole, anastrozole, exemestane) that lower oestrogen levels after menopause."),
    ("CDK4/6 inhibitor", r"\bCDK ?4/6\b|\bpalbociclib\b|\bribociclib\b|\babemaciclib\b", "Tablets (palbociclib, ribociclib, abemaciclib) that slow cancer cell division; usually combined with hormone therapy."),
    ("PARP inhibitor", r"\bPARP\b|\bolaparib\b|\bniraparib\b|\btalazoparib\b", "Tablets that stop cancer cells with BRCA changes from repairing their DNA."),
    ("Antibody-drug conjugate (ADC)", r"\bantibody[- ]drug conjugates?\b|\bADC\b|\bderuxtecan\b|\bgovitecan\b|\bemtansine\b|\bT-DXd\b|\bT-DM1\b", "An antibody that carries chemotherapy directly to cancer cells (for example T-DXd, T-DM1, sacituzumab govitecan)."),
    ("Monoclonal antibody", r"\bmonoclonal antibod(y|ies)\b|\b\w+mab\b", "A laboratory-made protein that attaches to a specific target on cells; drug names often end in -mab."),
    ("Taxane", r"\btaxanes?\b|\bpaclitaxel\b|\bdocetaxel\b", "A group of chemotherapy drugs (paclitaxel, docetaxel, nab-paclitaxel) widely used in breast cancer."),
    ("Anthracycline", r"\banthracyclines?\b|\bdoxorubicin\b|\bepirubicin\b", "A group of chemotherapy drugs (doxorubicin, epirubicin) that can affect the heart, so heart tests are required."),
    ("Biosimilar", r"\bbiosimilars?\b", "A medicine that is highly similar to an approved biological drug (for example a trastuzumab copy)."),
    # outcomes
    ("Endpoint", r"\bend ?points?\b", "The result that a study measures to decide whether a treatment works."),
    ("Primary endpoint", r"\bprimary end ?point\b", "The main result the study is designed to answer."),
    ("Secondary endpoint", r"\bsecondary end ?points?\b", "Additional results measured to learn more about the treatment."),
    ("Progression-free survival (PFS)", r"\bprogression[- ]free survival\b|\bPFS\b", "How long people live without the cancer growing or spreading."),
    ("Overall survival (OS)", r"\boverall survival\b|\bOS\b", "How long people live after starting treatment, from any cause."),
    ("Objective response rate (ORR)", r"\b(objective|overall) response rate\b|\bORR\b", "The share of people whose tumours shrink by a set amount."),
    ("Duration of response (DOR)", r"\bduration of response\b|\bDOR\b", "How long a tumour stays shrunk after it responds."),
    ("Clinical benefit rate (CBR)", r"\bclinical benefit rate\b|\bCBR\b", "The share of people whose cancer shrinks or stays stable for a set time."),
    ("Pathological complete response (pCR)", r"\bpathologic(al)? complete response\b|\bpCR\b", "No invasive cancer is left in the breast or lymph nodes at surgery after pre-surgery treatment."),
    ("Invasive disease-free survival (iDFS)", r"\binvasive disease[- ]free survival\b|\biDFS\b", "How long people stay free of the cancer returning or a new invasive cancer."),
    ("RECIST", r"\bRECIST\b", "Standard rules for measuring tumours on scans to decide whether they shrank, stayed stable or grew."),
    ("Hazard ratio", r"\bhazard ratios?\b", "A number comparing the risk of an event between two groups; below 1 means lower risk in the treated group."),
    ("Kaplan-Meier", r"\bKaplan[- ]Meier\b", "A standard graph and method for showing how many people remain event-free over time."),
    ("Sample size", r"\bsample size\b", "The number of participants the study plans to enrol."),
    # safety
    ("Adverse event (AE)", r"\badverse events?\b|\bAEs?\b", "Any unwanted medical problem that happens during the study, whether or not it is caused by the treatment."),
    ("Serious adverse event (SAE)", r"\bserious adverse events?\b|\bSAEs?\b", "A side effect that is life-threatening, needs hospital care, or causes lasting harm."),
    ("CTCAE", r"\bCTCAE\b", "The standard scale for grading side effects from 1 (mild) to 5 (death)."),
    ("Neutropenia", r"\bneutropeni", "A low number of neutrophils (infection-fighting white blood cells)."),
    ("Peripheral neuropathy", r"\bperipheral neuropathy\b|\bneuropathy\b", "Nerve damage causing numbness, tingling or pain, usually in the hands and feet."),
    ("Pneumonitis / ILD", r"\bpneumonitis\b|\binterstitial lung disease\b|\bILD\b", "Inflammation of the lungs; a serious side effect of some drugs that must be watched closely."),
    ("Cardiotoxicity / LVEF", r"\bcardiotoxicity\b|\bLVEF\b|\bejection fraction\b", "Heart damage from treatment; LVEF is the heart's pumping strength measured by a scan."),
    ("Immune-related adverse events", r"\bimmune[- ]related adverse\b|\birAEs?\b", "Side effects caused when immunotherapy makes the immune system attack healthy organs."),
    ("Data monitoring committee", r"\bdata (safety )?monitoring committee\b|\bIDMC\b|\bDSMB\b", "An independent expert group that reviews safety data during the study."),
]

# Plain-language meaning of the drug classes used by the curated terminology (lexicon.py).
CLASS_PLAIN = {
    "PD-1 inhibitor": "an immunotherapy antibody that blocks the PD-1 'brake' on immune cells so they can attack cancer",
    "PD-L1 inhibitor": "an immunotherapy antibody that blocks PD-L1 on cancer cells so immune cells can attack them",
    "CTLA-4 inhibitor": "an immunotherapy antibody that boosts immune T-cells by blocking CTLA-4",
    "CDK4/6 inhibitor": "a tablet that slows cancer cell division, usually given with hormone therapy",
    "PARP inhibitor": "a tablet that stops cancer cells with BRCA changes from repairing their DNA",
    "Aromatase inhibitor": "a hormone tablet that lowers oestrogen levels after menopause",
    "Selective estrogen receptor modulator": "a hormone drug that blocks oestrogen receptors in breast tissue (for example tamoxifen)",
    "Selective estrogen receptor degrader": "a hormone drug that blocks and breaks down the oestrogen receptor (for example fulvestrant)",
    "HER2-targeted monoclonal antibody": "an antibody that attaches to HER2 on cancer cells and blocks their growth signal",
    "HER2 tyrosine kinase inhibitor": "a tablet that blocks the HER2 growth signal inside cancer cells",
    "Antibody-drug conjugate": "an antibody that carries chemotherapy directly to cancer cells",
    "Taxane": "chemotherapy that stops cancer cells from dividing",
    "Anthracycline": "chemotherapy that damages cancer-cell DNA; the heart is monitored because it can be affected",
    "Platinum agent": "chemotherapy (such as carboplatin) that damages cancer-cell DNA",
    "Cytotoxic chemotherapy": "medicine that kills fast-dividing cells, including cancer cells",
    "Antimetabolite": "chemotherapy that interferes with how cells build DNA (such as capecitabine or gemcitabine)",
    "Alkylating agent": "chemotherapy that damages DNA (such as cyclophosphamide)",
    "Non-taxane microtubule inhibitor": "chemotherapy that stops cell division (such as eribulin or vinorelbine)",
    "Topoisomerase inhibitor": "chemotherapy that blocks the enzymes cells use to copy DNA",
    "PI3K inhibitor": "a tablet that blocks the PI3K growth pathway, used for PIK3CA-mutated cancers",
    "AKT inhibitor": "a tablet that blocks the AKT growth pathway",
    "mTOR inhibitor": "a tablet that blocks the mTOR growth pathway (such as everolimus)",
    "VEGF / angiogenesis inhibitor": "a drug that blocks the blood-vessel growth tumours need",
    "GnRH agonist / antagonist (ovarian function suppression)": "an injection that switches off oestrogen production by the ovaries",
    "Granulocyte colony-stimulating factor": "a supportive injection that raises white blood cells to prevent infections",
    "Bone-modifying agent": "a drug that protects the bones (such as zoledronic acid or denosumab)",
    "HDAC inhibitor": "a drug that changes how genes are switched on in cancer cells",
    "Therapeutic cancer vaccine": "a vaccine that trains the immune system to recognise cancer",
    "Cellular therapy": "treatment made from immune cells that are grown or modified in a laboratory",
    "Androgen receptor-directed agent": "a drug that blocks the androgen (male hormone) receptor on cancer cells",
}


def drug_reference(drug_ids: list[str]) -> list[dict]:
    """Reference terminology (not protocol evidence) for the drugs a protocol investigates."""
    from app.extraction import lexicon as L
    out = []
    for did in drug_ids:
        c = L.BY_ID.get(did)
        if not c or c.type not in ("Drug", "CombinationTherapy"):
            continue
        classes = [L.BY_ID[k].name for k in c.classes if k in L.BY_ID]
        expl = "; ".join(f"{k}: {CLASS_PLAIN[k]}" for k in classes if k in CLASS_PLAIN)
        out.append({"drug": c.name, "classes": classes, "explanation": expl or None, "other_names": [a for a in c.aliases[:4]]})
    return out


_COMPILED = [(t, re.compile(p, re.I), d) for t, p, d in _G]


def explain_terms(text: str, limit: int = 40) -> list[dict]:
    """Return glossary entries whose terms occur in the text, in glossary order."""
    out = []
    for term, rx, desc in _COMPILED:
        if rx.search(text):
            out.append({"term": term, "explanation": desc})
            if len(out) >= limit:
                break
    return out


def as_reference(entries: list[dict]) -> str:
    return "\n".join(f"- {e['term']}: {e['explanation']}" for e in entries)
