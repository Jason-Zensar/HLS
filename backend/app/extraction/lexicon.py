"""Curated breast-oncology terminology resource.

This is the synonym dictionary used for entity recognition and canonicalisation. It maps
generic names, brand names, development codes and abbreviations to one canonical concept.
It was compiled for this project from public nomenclature (INN / USAN names, FDA labels,
CTCAE terms, RECIST / STEEP endpoint definitions). It is NOT UMLS, RxNorm or MeSH; those
resources require separate licences and can be plugged into `resolution/resolver.py`.

Design rules
* Distinct molecules are distinct concepts even when names overlap
  (trastuzumab != trastuzumab emtansine != trastuzumab deruxtecan; tamoxifen != endoxifen).
* Short / ambiguous abbreviations are case-sensitive and may require a context pattern
  (e.g. "PR" only means progesterone receptor near ER/HER2/positive/negative wording,
  otherwise it is usually "partial response").
* Drug-class membership here is reference terminology; graph edges derived from it are
  labelled assertion_type="terminology" so the UI never presents them as protocol evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Concept:
    id: str
    type: str                      # graph label, e.g. Drug, Biomarker
    name: str
    aliases: list[str] = field(default_factory=list)
    cs_aliases: list[str] = field(default_factory=list)   # case-sensitive aliases
    context: str | None = None     # regex that must occur within +-60 chars for cs aliases
    neg_context: str | None = None  # regex that must NOT occur within +-40 chars for cs aliases
    classes: list[str] = field(default_factory=list)      # DrugClass ids
    extra_labels: list[str] = field(default_factory=list)
    props: dict = field(default_factory=dict)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


CONCEPTS: list[Concept] = []


def _add(type_: str, prefix: str, name: str, aliases=(), cs=(), classes=(), context=None, labels=(), neg=None, **props):
    c = Concept(id=f"{prefix}:{slug(name)}", type=type_, name=name, aliases=list(aliases), cs_aliases=list(cs),
                context=context, neg_context=neg, classes=list(classes), extra_labels=list(labels), props=props)
    CONCEPTS.append(c)
    return c


# ---------------------------------------------------------------------------
# Drug classes (with parent class for hierarchy queries such as "chemotherapy")
# ---------------------------------------------------------------------------
DRUG_CLASSES = {
    "chemotherapy": ("Cytotoxic chemotherapy", None),
    "taxane": ("Taxane", "chemotherapy"),
    "anthracycline": ("Anthracycline", "chemotherapy"),
    "platinum": ("Platinum agent", "chemotherapy"),
    "alkylating": ("Alkylating agent", "chemotherapy"),
    "antimetabolite": ("Antimetabolite", "chemotherapy"),
    "microtubule": ("Non-taxane microtubule inhibitor", "chemotherapy"),
    "topoisomerase": ("Topoisomerase inhibitor", "chemotherapy"),
    "her2-mab": ("HER2-targeted monoclonal antibody", "targeted"),
    "her2-tki": ("HER2 tyrosine kinase inhibitor", "targeted"),
    "adc": ("Antibody-drug conjugate", "targeted"),
    "cdk46": ("CDK4/6 inhibitor", "targeted"),
    "pi3k": ("PI3K inhibitor", "targeted"),
    "akt": ("AKT inhibitor", "targeted"),
    "mtor": ("mTOR inhibitor", "targeted"),
    "parp": ("PARP inhibitor", "targeted"),
    "vegf": ("VEGF / angiogenesis inhibitor", "targeted"),
    "hdac": ("HDAC inhibitor", "targeted"),
    "fgfr": ("FGFR inhibitor", "targeted"),
    "tki-other": ("Other kinase inhibitor", "targeted"),
    "targeted": ("Targeted therapy", None),
    "pd1": ("PD-1 inhibitor", "immunotherapy"),
    "pdl1": ("PD-L1 inhibitor", "immunotherapy"),
    "ctla4": ("CTLA-4 inhibitor", "immunotherapy"),
    "io-other": ("Other immunomodulator", "immunotherapy"),
    "vaccine": ("Therapeutic cancer vaccine", "immunotherapy"),
    "cell-therapy": ("Cellular therapy", "immunotherapy"),
    "immunotherapy": ("Immunotherapy", None),
    "ai": ("Aromatase inhibitor", "endocrine"),
    "serm": ("Selective estrogen receptor modulator", "endocrine"),
    "serd": ("Selective estrogen receptor degrader", "endocrine"),
    "gnrh": ("GnRH agonist / antagonist (ovarian function suppression)", "endocrine"),
    "ar": ("Androgen receptor-directed agent", "endocrine"),
    "endocrine": ("Endocrine therapy", None),
    "bone": ("Bone-modifying agent", "supportive"),
    "gcsf": ("Granulocyte colony-stimulating factor", "supportive"),
    "supportive": ("Supportive-care agent", None),
    "radiopharm": ("Radiopharmaceutical", None),
    "other": ("Other agent", None),
}
for cid, (cname, parent) in DRUG_CLASSES.items():
    _add("DrugClass", "class", cname, props={"class_key": cid, "parent": parent})
CLASS_ID = {k: f"class:{slug(v[0])}" for k, v in DRUG_CLASSES.items()}
CLASS_PARENT = {CLASS_ID[k]: (CLASS_ID[v[1]] if v[1] else None) for k, v in DRUG_CLASSES.items()}


def drug(name, aliases=(), cs=(), cls=("other",), context=None, **props):
    return _add("Drug", "drug", name, aliases, cs, [CLASS_ID[c] for c in cls], context, **props)


# --- HER2-directed ---------------------------------------------------------------
drug("trastuzumab", ["herceptin", "herceptin sc", "trastuzumab sc", "subcutaneous trastuzumab", "trastuzumab iv"], cls=["her2-mab"])
drug("pertuzumab", ["perjeta", "rg1273"], cls=["her2-mab"])
drug("pertuzumab, trastuzumab and hyaluronidase", ["phesgo", "ph fdc sc", "ph fdc", "pertuzumab/trastuzumab fixed-dose combination",
     "fixed-dose combination of pertuzumab and trastuzumab", "pertuzumab and trastuzumab fixed-dose combination"], cls=["her2-mab"])
drug("trastuzumab emtansine", ["ado-trastuzumab emtansine", "kadcyla", "trastuzumab-emtansine", "trastuzumab-mcc-dm1"], ["T-DM1", "TDM1", "TDM-1"], cls=["adc"])
drug("trastuzumab deruxtecan", ["fam-trastuzumab deruxtecan-nxki", "fam-trastuzumab deruxtecan", "enhertu", "ds-8201a", "ds-8201", "ds8201a", "ds8201"], ["T-DXd", "TDXd"], cls=["adc"])
drug("trastuzumab duocarmazine", ["syd985"], cls=["adc"])
drug("trastuzumab rezetecan", ["shr-a1811"], cls=["adc"])
drug("disitamab vedotin", ["rc48", "rc48-adc"], cls=["adc"])
drug("margetuximab", ["margenza"], cls=["her2-mab"])
drug("zanidatamab", ["zw25"], cls=["her2-mab"])
drug("lapatinib", ["tykerb", "tyverb", "gw572016"], cls=["her2-tki"])
drug("neratinib", ["nerlynx", "hki-272"], cls=["her2-tki"])
drug("tucatinib", ["tukysa", "ont-380", "arry-380"], cls=["her2-tki"])
drug("pyrotinib", [], cls=["her2-tki"])
# --- CDK4/6 ---------------------------------------------------------------------
drug("palbociclib", ["ibrance", "pd-0332991", "pd0332991"], cls=["cdk46"])
drug("ribociclib", ["kisqali", "lee011", "lee-011"], cls=["cdk46"])
drug("abemaciclib", ["verzenio", "verzenios", "ly2835219"], cls=["cdk46"])
drug("dalpiciclib", ["shr6390"], cls=["cdk46"])
drug("trilaciclib", ["cosela", "g1t28"], cls=["cdk46", "supportive"])
# --- Endocrine ---------------------------------------------------------------------
drug("tamoxifen", ["nolvadex", "tamoxifen citrate"], cls=["serm"])
drug("4-hydroxytamoxifen", ["afimoxifene", "4-oht", "4-hydroxy tamoxifen", "4hydroxytamoxifen"], cls=["serm"])
drug("endoxifen", ["z-endoxifen", "(z)-endoxifen"], cls=["serm"])
drug("toremifene", ["fareston"], cls=["serm"])
drug("raloxifene", ["evista"], cls=["serm"])
drug("lasofoxifene", [], cls=["serm"])
drug("letrozole", ["femara"], cls=["ai"])
drug("anastrozole", ["arimidex"], cls=["ai"])
drug("exemestane", ["aromasin"], cls=["ai"])
drug("fulvestrant", ["faslodex"], cls=["serd"])
drug("elacestrant", ["orserdu", "rad1901"], cls=["serd"])
drug("camizestrant", ["azd9833"], cls=["serd"])
drug("giredestrant", ["gdc-9545"], cls=["serd"])
drug("imlunestrant", ["ly3484356"], cls=["serd"])
drug("amcenestrant", ["sar439859"], cls=["serd"])
drug("vepdegestrant", ["arv-471"], cls=["serd"])
drug("goserelin", ["zoladex", "goserelin acetate"], cls=["gnrh"])
drug("leuprolide", ["leuprorelin", "lupron", "leuprolide acetate"], cls=["gnrh"])
drug("triptorelin", ["decapeptyl", "trelstar"], cls=["gnrh"])
drug("degarelix", ["firmagon"], cls=["gnrh"])
drug("megestrol acetate", ["megestrol", "megace"], cls=["endocrine"])
drug("enobosarm", ["gtx-024", "ostarine"], cls=["ar"])
drug("enzalutamide", ["xtandi", "mdv3100"], cls=["ar"])
drug("bicalutamide", ["casodex"], cls=["ar"])
# --- PI3K / AKT / mTOR -------------------------------------------------------------------
drug("alpelisib", ["piqray", "byl719", "byl-719"], cls=["pi3k"])
drug("inavolisib", ["gdc-0077", "itovebi"], cls=["pi3k"])
drug("taselisib", ["gdc-0032"], cls=["pi3k"])
drug("buparlisib", ["bkm120"], cls=["pi3k"])
drug("gedatolisib", ["pf-05212384"], cls=["pi3k"])
drug("capivasertib", ["truqap", "azd5363"], cls=["akt"])
drug("ipatasertib", ["gdc-0068"], cls=["akt"])
drug("everolimus", ["afinitor", "rad001"], cls=["mtor"])
drug("sapanisertib", ["tak-228", "mln0128"], cls=["mtor"])
# --- PARP -------------------------------------------------------------------------------
drug("olaparib", ["lynparza", "azd2281", "ku-0059436"], cls=["parp"])
drug("talazoparib", ["talzenna", "bmn 673", "bmn673"], cls=["parp"])
drug("niraparib", ["zejula", "mk-4827"], cls=["parp"])
drug("veliparib", ["abt-888"], cls=["parp"])
drug("rucaparib", ["rubraca"], cls=["parp"])
# --- Immunotherapy --------------------------------------------------------------------
drug("pembrolizumab", ["keytruda", "mk-3475", "lambrolizumab"], cls=["pd1"])
drug("nivolumab", ["opdivo", "bms-936558", "ono-4538"], cls=["pd1"])
drug("dostarlimab", ["jemperli"], cls=["pd1"])
drug("camrelizumab", ["shr-1210"], cls=["pd1"])
drug("toripalimab", [], cls=["pd1"])
drug("tislelizumab", [], cls=["pd1"])
drug("sintilimab", [], cls=["pd1"])
drug("spartalizumab", ["pdr001"], cls=["pd1"])
drug("cemiplimab", ["libtayo"], cls=["pd1"])
drug("atezolizumab", ["tecentriq", "mpdl3280a", "rg7446"], cls=["pdl1"])
drug("durvalumab", ["imfinzi", "medi4736"], cls=["pdl1"])
drug("avelumab", ["bavencio", "msb0010718c"], cls=["pdl1"])
drug("ipilimumab", ["yervoy"], cls=["ctla4"])
drug("tremelimumab", [], cls=["ctla4"])
drug("utomilumab", ["pf-05082566"], cls=["io-other"])
drug("rintatolimod", ["ampligen"], cls=["io-other"])
drug("interferon alfa-2b", ["interferon alpha-2b", "ifn-a2b", "ifn-alpha-2b", "intron a"], cls=["io-other"])
drug("nelipepimut-S", ["neuvax", "e75 peptide"], cls=["vaccine"])
drug("ES2B-C001", ["es2b-c001"], cls=["vaccine"])
drug("P10s-PADRE vaccine", ["p10s-padre"], cls=["vaccine"])
drug("Montanide ISA 51", ["montanide"], cls=["vaccine"])
drug("LN-145 tumor-infiltrating lymphocytes", ["ln-145", "lifileucel"], cls=["cell-therapy"])
# --- Other ADCs -------------------------------------------------------------------------
drug("sacituzumab govitecan", ["trodelvy", "immu-132", "sacituzumab govitecan-hziy"], cls=["adc"])
drug("datopotamab deruxtecan", ["ds-1062", "ds-1062a", "datopotamab deruxtecan-dlnk", "datroway"], ["Dato-DXd"], cls=["adc"])
drug("patritumab deruxtecan", ["u3-1402", "her3-dxd"], cls=["adc"])
drug("sacituzumab tirumotecan", ["mk-2870", "skb264", "sac-tmt"], cls=["adc"])
drug("ladiratuzumab vedotin", ["sgn-liv1a"], cls=["adc"])
# --- Chemotherapy ------------------------------------------------------------------------
drug("paclitaxel", ["taxol", "solvent-based paclitaxel"], cls=["taxane"])
drug("nab-paclitaxel", ["abraxane", "nab paclitaxel", "albumin-bound paclitaxel", "nanoparticle albumin-bound paclitaxel",
     "paclitaxel protein-bound", "protein-bound paclitaxel", "nabpaclitaxel"], cls=["taxane"])
drug("docetaxel", ["taxotere"], cls=["taxane"])
drug("tesetaxel", [], cls=["taxane"])
drug("doxorubicin", ["adriamycin", "doxorubicin hydrochloride"], cls=["anthracycline"])
drug("pegylated liposomal doxorubicin", ["liposomal doxorubicin", "doxil", "caelyx", "pegylated liposomal doxorubicin hydrochloride", "lipodox"], ["PLD"], cls=["anthracycline"])
drug("epirubicin", ["ellence", "pharmorubicin"], cls=["anthracycline"])
drug("cyclophosphamide", ["cytoxan", "endoxan"], cls=["alkylating"])
drug("carboplatin", ["paraplatin"], cls=["platinum"])
drug("cisplatin", ["platinol"], cls=["platinum"])
drug("capecitabine", ["xeloda"], cls=["antimetabolite"])
drug("gemcitabine", ["gemzar"], cls=["antimetabolite"])
drug("fluorouracil", ["5-fluorouracil", "5-fu", "5fu"], cls=["antimetabolite"])
drug("methotrexate", [], cls=["antimetabolite"])
drug("eribulin", ["halaven", "eribulin mesylate", "e7389"], cls=["microtubule"])
drug("vinorelbine", ["navelbine", "oral vinorelbine"], cls=["microtubule"])
drug("ixabepilone", ["ixempra"], cls=["microtubule"])
drug("utidelone", [], cls=["microtubule"])
drug("irinotecan", ["camptosar"], cls=["topoisomerase"])
drug("etoposide", [], cls=["topoisomerase"])
drug("mitoxantrone", [], cls=["topoisomerase"])
# --- Angiogenesis / kinase / epigenetic -----------------------------------------------
drug("bevacizumab", ["avastin"], cls=["vegf"])
drug("ramucirumab", ["cyramza"], cls=["vegf"])
drug("apatinib", ["rivoceranib"], cls=["vegf"])
drug("anlotinib", [], cls=["vegf"])
drug("entinostat", ["ms-275", "snd-275"], cls=["hdac"])
drug("vorinostat", ["zolinza", "saha"], cls=["hdac"])
drug("tucidinostat", ["chidamide"], cls=["hdac"])
drug("dasatinib", ["sprycel"], cls=["tki-other"])
drug("Debio 1347", ["debio1347", "debio-1347", "zoligratinib"], cls=["fgfr"])
drug("galunisertib", ["ly2157299"], cls=["tki-other"])
drug("TRC105", ["carotuximab", "trc-105"], cls=["vegf"])
drug("PEGPH20", ["pegvorhyaluronidase alfa", "pegph-20"], cls=["other"])
# --- Bone / supportive / other -------------------------------------------------------------
drug("denosumab", ["xgeva", "prolia", "amg 162"], cls=["bone"])
drug("zoledronic acid", ["zoledronate", "zometa", "reclast"], cls=["bone"])
drug("pamidronate", ["aredia"], cls=["bone"])
drug("filgrastim", ["neupogen", "g-csf"], cls=["gcsf"])
drug("pegfilgrastim", ["neulasta", "peg-filgrastim"], cls=["gcsf"])
drug("efbemalenograstim alfa", ["f-627", "ryzneuta"], cls=["gcsf"])
drug("radium-223 dichloride", ["radium-223", "radium 223", "xofigo", "ra-223", "223ra"], cls=["radiopharm"])
drug("elinzanetant", ["bay 3427080", "nt-814"], cls=["supportive"])
drug("celecoxib", ["celebrex"], cls=["other"])
drug("metformin", ["glucophage"], cls=["other"])
drug("aspirin", ["acetylsalicylic acid"], cls=["other"])
drug("cholecalciferol", ["vitamin d3", "vitamin d 3"], cls=["supportive"])
drug("omega-3 fatty acids", ["omega-3 pufa", "omega-3 polyunsaturated fatty acids", "n-3 pufa", "fish oil"], cls=["supportive"])
drug("carvedilol", ["coreg"], cls=["supportive"])
drug("dexamethasone", ["decadron"], cls=["supportive"])
drug("cabozantinib", ["cabometyx"], cls=["tki-other"])
drug("sunitinib", ["sutent"], cls=["tki-other"])

# Generic intervention concepts (used for "X combined with chemotherapy" style statements)
_add("Intervention", "intervention", "chemotherapy", ["chemotherapy", "cytotoxic chemotherapy", "systemic chemotherapy"])
_add("Intervention", "intervention", "endocrine therapy", ["endocrine therapy", "hormonal therapy", "hormone therapy", "endocrine treatment"], ["ET"],
     context=r"(endocrine|hormon|aromatase|tamoxifen|letrozole|fulvestrant|CDK4/6|\+\s*ET|ET\s*\+)")
_add("Intervention", "intervention", "radiotherapy", ["radiotherapy", "radiation therapy", "whole brain radiotherapy", "stereotactic radiosurgery"], ["WBRT", "SRS"])
_add("Intervention", "intervention", "surgery", ["breast surgery", "mastectomy", "lumpectomy", "breast-conserving surgery", "axillary lymph node dissection", "sentinel lymph node biopsy"])
_add("Intervention", "intervention", "ovarian function suppression", ["ovarian function suppression", "ovarian suppression"], ["OFS"])
_add("Intervention", "intervention", "cryoablation", ["cryoablation"])
_add("Intervention", "intervention", "investigator's choice chemotherapy", ["investigator's choice chemotherapy", "treatment of physician's choice", "physician's choice", "investigator's choice"], ["TPC"])

# Regimen abbreviations - case-sensitive, require oncology context
_REG_CTX = r"(cycle|dose-dense|dd|followed by|q[23]w|every|mg/m|regimen|anthracycline|taxane|paclitaxel|docetaxel|neoadjuvant|adjuvant)"
_add("CombinationTherapy", "regimen", "AC (doxorubicin + cyclophosphamide)", ["doxorubicin and cyclophosphamide", "doxorubicin plus cyclophosphamide", "adriamycin and cyclophosphamide"], ["AC", "ddAC"], context=_REG_CTX, components=["drug:doxorubicin", "drug:cyclophosphamide"])
_add("CombinationTherapy", "regimen", "EC (epirubicin + cyclophosphamide)", ["epirubicin and cyclophosphamide", "epirubicin plus cyclophosphamide"], ["EC", "ddEC"], context=_REG_CTX, components=["drug:epirubicin", "drug:cyclophosphamide"])
_add("CombinationTherapy", "regimen", "FEC (fluorouracil + epirubicin + cyclophosphamide)", [], ["FEC", "FEC100", "FEC 100"], context=_REG_CTX, components=["drug:fluorouracil", "drug:epirubicin", "drug:cyclophosphamide"])
_add("CombinationTherapy", "regimen", "TC (docetaxel + cyclophosphamide)", ["docetaxel and cyclophosphamide"], ["TC"], context=r"(docetaxel|cyclophosphamide|cycles?\b|q3w|regimen)", components=["drug:docetaxel", "drug:cyclophosphamide"])
_add("CombinationTherapy", "regimen", "TCHP (docetaxel + carboplatin + trastuzumab + pertuzumab)", [], ["TCHP"], components=["drug:docetaxel", "drug:carboplatin", "drug:trastuzumab", "drug:pertuzumab"])
_add("CombinationTherapy", "regimen", "TCH (docetaxel + carboplatin + trastuzumab)", [], ["TCH"], context=_REG_CTX + r"|trastuzumab", components=["drug:docetaxel", "drug:carboplatin", "drug:trastuzumab"])
_add("CombinationTherapy", "regimen", "TAC (docetaxel + doxorubicin + cyclophosphamide)", [], ["TAC"], context=_REG_CTX, components=["drug:docetaxel", "drug:doxorubicin", "drug:cyclophosphamide"])

# ---------------------------------------------------------------------------
# Biomarkers / genes / proteins / molecular targets
# ---------------------------------------------------------------------------
def biomarker(name, aliases=(), cs=(), context=None, labels=(), neg=None, **props):
    return _add("Biomarker", "biomarker", name, aliases, cs, (), context, labels, neg, **props)


_RECEPTOR_CTX = r"(HER2|ERBB2|ER\b|PgR|PR\b|HR\b|hormone|receptor|positive|negative|\+|-positive|-negative|status|IHC|%|express)"
biomarker("HER2", ["her2/neu", "her-2", "her 2", "erbb2", "erbb-2", "human epidermal growth factor receptor 2", "her2 status", "her2 expression"], ["HER2"], labels=["Protein"], kind="protein/gene")
biomarker("HER2-low expression", ["her2-low", "her2 low", "her2-low expression", "her2 ihc 1+", "her2-ultralow", "her2 ultralow"], labels=["Protein"], kind="expression level")
biomarker("Estrogen receptor (ER)", ["estrogen receptor", "oestrogen receptor", "er-positive", "er positive", "er-negative", "er negative", "er+", "er status", "er expression"], ["ER"], context=_RECEPTOR_CTX, labels=["Protein"], neg=r"(emergency|ER visit)", kind="protein")
biomarker("Progesterone receptor (PgR)", ["progesterone receptor", "pgr", "pr-positive", "pr positive", "pr-negative", "pr negative", "pgr-positive"], ["PR", "PgR"], context=_RECEPTOR_CTX, labels=["Protein"],
          neg=r"(partial response|complete response|partial remission|CR|SD|PD|ORR|CR\s*\+\s*PR|CR\s*or\s*PR|PR\s*or\s*CR|response)", kind="protein")
biomarker("Hormone receptor (HR) status", ["hormone receptor", "hormone-receptor", "hr-positive", "hr positive", "hr-negative", "hr negative", "hr+", "hormone receptor-positive", "hormone receptor positive"], labels=["Protein"], kind="protein")
biomarker("Ki-67", ["ki67", "ki 67", "mib-1", "ki-67 index", "ki67 index"], labels=["Protein"], kind="proliferation marker")
biomarker("PD-L1", ["pd-l1", "pdl1", "programmed death-ligand 1", "programmed death ligand 1", "pd-l1 expression", "combined positive score", "pd-l1 cps"], ["CPS"], context=r"(PD-L1|pembrolizumab|22C3|SP142|score)", labels=["Protein"], kind="protein")
biomarker("BRCA1", ["brca1", "brca 1"], labels=["Gene"], kind="gene")
biomarker("BRCA2", ["brca2", "brca 2"], labels=["Gene"], kind="gene")
biomarker("BRCA1/2 mutation", ["brca mutation", "brca1/2 mutation", "brca-mutated", "brca mutated", "gbrca", "gbrcam", "germline brca", "gbrca mutation", "brca1/2", "brcam", "brca-mutant", "gbrcamut", "brca1 or brca2 mutation"], labels=["Gene"], kind="genomic alteration")
biomarker("PIK3CA", ["pik3ca", "pik3ca mutation", "pik3ca-mutated", "pik3ca mutated", "pik3ca-mutant"], labels=["Gene"], kind="gene")
biomarker("ESR1", ["esr1", "esr1 mutation", "esr1-mutated", "esr1m"], labels=["Gene"], kind="gene")
biomarker("AKT1", ["akt1", "akt1 mutation"], labels=["Gene"], kind="gene")
biomarker("PTEN", ["pten", "pten loss"], labels=["Gene"], kind="gene")
biomarker("TP53", ["tp53", "p53"], labels=["Gene"], kind="gene")
biomarker("PALB2", ["palb2"], labels=["Gene"], kind="gene")
biomarker("ATM", [], ["ATM"], context=r"(mutation|gene|germline|BRCA|PALB2|CHEK2)", labels=["Gene"], kind="gene")
biomarker("CHEK2", ["chek2"], labels=["Gene"], kind="gene")
biomarker("Androgen receptor (AR)", ["androgen receptor", "ar-positive", "ar positive", "ar+"], ["AR"], context=r"(androgen|AR\+|AR-positive|enzalutamide|enobosarm|express|IHC|%)", labels=["Protein"], kind="protein")
biomarker("Tumor-infiltrating lymphocytes (TILs)", ["tumor-infiltrating lymphocytes", "tumour-infiltrating lymphocytes", "tumor infiltrating lymphocytes", "stromal tils"], ["TILs", "sTILs"], kind="immune marker")
biomarker("Circulating tumor DNA (ctDNA)", ["ctdna", "circulating tumor dna", "circulating tumour dna", "cell-free dna", "cfdna"], kind="liquid biopsy")
biomarker("Homologous recombination deficiency (HRD)", ["homologous recombination deficiency", "hrd score", "hrd-positive"], ["HRD"], kind="genomic signature")
biomarker("Oncotype DX recurrence score", ["oncotype dx", "oncotype", "21-gene recurrence score", "recurrence score", "21-gene assay"], kind="gene expression signature")
biomarker("MammaPrint", ["mammaprint", "70-gene signature"], kind="gene expression signature")
biomarker("PAM50 intrinsic subtype", ["pam50", "prosigna", "intrinsic subtype"], kind="gene expression signature")
biomarker("TROP2", ["trop2", "trop-2", "tacstd2"], labels=["Protein"], kind="protein")
biomarker("HER3", ["her3", "erbb3"], labels=["Protein"], kind="protein")
biomarker("FGFR1 amplification", ["fgfr1 amplification", "fgfr amplification", "fgfr-amplified", "fgfr1-amplified", "fgfr1"], labels=["Gene"], kind="gene")
biomarker("Tumor mutational burden (TMB)", ["tumor mutational burden", "tumour mutational burden"], ["TMB"], kind="genomic signature")
biomarker("Microsatellite instability / dMMR", ["microsatellite instability", "msi-high", "msi-h", "mismatch repair deficient", "dmmr"], kind="genomic signature")
biomarker("CA 15-3", ["ca 15-3", "ca15-3", "cancer antigen 15-3"], labels=["Protein"], kind="serum marker")
biomarker("Hyaluronan (HA-high)", ["hyaluronan", "ha-high", "hyaluronic acid level"], kind="tumor matrix marker")
biomarker("RB1", ["rb1", "retinoblastoma protein"], labels=["Gene"], kind="gene")
biomarker("Cyclin E1 (CCNE1)", ["ccne1", "cyclin e1"], labels=["Gene"], kind="gene")
biomarker("SUV (PET standardized uptake value)", ["standardized uptake value", "suvmax", "fdg-pet suv"], ["SUV"], context=r"(PET|FDG|uptake)", kind="imaging biomarker")

# Molecular targets (only linked from protocol text, e.g. "pembrolizumab, an anti-PD-1 antibody")
def target(name, aliases=(), cs=()):
    return _add("MolecularTarget", "target", name, aliases, cs)


target("HER2 receptor", ["her2", "erbb2"])
target("PD-1", ["pd-1", "programmed cell death protein 1", "programmed death-1", "programmed death 1"])
target("PD-L1 ligand", ["pd-l1"])
target("CTLA-4", ["ctla-4", "ctla4"])
target("CDK4/6", ["cdk4/6", "cdk 4/6", "cyclin-dependent kinase 4/6", "cyclin-dependent kinases 4 and 6", "cdk4 and cdk6"])
target("PI3K alpha", ["pi3k", "pi3kα", "pi3k-alpha", "phosphatidylinositol 3-kinase", "p110α", "p110alpha"])
target("AKT", ["akt"])
target("mTOR", ["mtor", "mammalian target of rapamycin"])
target("PARP", ["parp", "poly(adp-ribose) polymerase", "poly (adp-ribose) polymerase"])
target("Aromatase", ["aromatase"])
target("Estrogen receptor alpha", ["estrogen receptor", "erα", "er-alpha"])
target("TROP2 antigen", ["trop-2", "trop2"])
target("Topoisomerase I", ["topoisomerase i", "topoisomerase 1", "topo-i", "topoisomerase-i"])
target("VEGF-A", ["vegf", "vegf-a", "vascular endothelial growth factor"])
target("RANKL", ["rankl", "rank ligand"])
target("FGFR", ["fgfr", "fgfr1-3", "fibroblast growth factor receptor"])
target("Androgen receptor target", ["androgen receptor"])
target("HER3 receptor", ["her3"])
target("GnRH receptor", ["gnrh receptor", "lhrh receptor", "gonadotropin-releasing hormone receptor"])
target("HDAC", ["hdac", "histone deacetylase"])
target("Microtubules", ["microtubules", "tubulin"])

# ---------------------------------------------------------------------------
# Diseases, subtypes, settings
# ---------------------------------------------------------------------------
_add("Disease", "disease", "Breast cancer", ["breast cancer", "breast carcinoma", "carcinoma of the breast", "breast neoplasm", "mammary carcinoma"])
for nm, al in [("Non-small cell lung cancer", ["non-small cell lung cancer", "non-small-cell lung cancer", "nsclc"]),
               ("Ovarian cancer", ["ovarian cancer"]), ("Gastric cancer", ["gastric cancer", "gastroesophageal junction"]),
               ("Melanoma", ["melanoma"]), ("Prostate cancer", ["prostate cancer"]), ("Colorectal cancer", ["colorectal cancer"]),
               ("Endometrial cancer", ["endometrial cancer", "uterine cancer"]), ("Solid tumors", ["solid tumors", "solid tumours", "advanced solid tumors"]),
               ("Pancreatic cancer", ["pancreatic cancer"]), ("Bladder cancer", ["urothelial carcinoma", "bladder cancer"])]:
    _add("Disease", "disease", nm, al)


def subtype(name, aliases=(), cs=(), context=None):
    return _add("CancerSubtype", "subtype", name, aliases, cs, (), context)


subtype("Triple-negative breast cancer", ["triple-negative breast cancer", "triple negative breast cancer", "triple-negative", "triple negative", "tnbc", "er-/pr-/her2-"], ["TNBC", "mTNBC", "eTNBC"])
subtype("HER2-positive breast cancer", ["her2-positive breast cancer", "her2 positive breast cancer", "her2-positive", "her2 positive", "her2+", "her2-overexpressing", "her2-amplified", "her2 overexpressing", "her2+ bc", "her2+ mbc"])
subtype("HER2-low breast cancer", ["her2-low breast cancer", "her2 low breast cancer", "her2-low metastatic breast cancer"])
subtype("HR-positive / HER2-negative breast cancer", ["hr+/her2-", "hr-positive/her2-negative", "hr positive/her2 negative", "hormone receptor-positive, her2-negative",
        "hr+, her2-", "er+/her2-", "er-positive/her2-negative", "er positive/her2 negative", "hr+/her2- breast cancer", "luminal breast cancer",
        "hormone receptor-positive/human epidermal growth factor receptor 2-negative", "hr-positive, her2-negative", "er+/her2- breast cancer"])
subtype("HR-positive / HER2-positive breast cancer", ["hr+/her2+", "hr-positive/her2-positive", "er+/her2+", "triple-positive", "triple positive"])
subtype("Inflammatory breast cancer", ["inflammatory breast cancer"], ["IBC"], context=r"(inflammatory|breast)")
subtype("Invasive lobular carcinoma", ["invasive lobular carcinoma", "lobular breast cancer", "lobular carcinoma"])
subtype("Ductal carcinoma in situ", ["ductal carcinoma in situ"], ["DCIS"])
subtype("Breast cancer brain metastases", ["brain metastases", "brain metastasis", "cns metastases", "central nervous system metastases", "brain mets", "leptomeningeal disease", "leptomeningeal metastases"])
subtype("Metastatic breast cancer", ["metastatic breast cancer", "advanced breast cancer", "locally advanced or metastatic breast cancer", "advanced or metastatic breast cancer", "unresectable or metastatic breast cancer"], ["MBC", "ABC", "aBC", "mBC"], context=r"(breast|MBC|ABC|metasta|advanced)")
subtype("Early breast cancer", ["early breast cancer", "early-stage breast cancer", "early stage breast cancer", "operable breast cancer"], ["EBC", "eBC"])
subtype("Male breast cancer", ["male breast cancer"])


def setting(name, aliases=(), cs=()):
    return _add("TreatmentSetting", "setting", name, aliases, cs)


setting("Neoadjuvant", ["neoadjuvant", "neo-adjuvant", "preoperative", "pre-operative", "presurgical", "pre-surgical"])
setting("Adjuvant", ["adjuvant", "postoperative adjuvant", "post-operative"])
setting("Metastatic / advanced", ["metastatic setting", "advanced setting", "metastatic disease", "unresectable", "advanced disease", "locally advanced"])
setting("First-line", ["first-line", "first line", "1st line", "frontline", "treatment-naive"], ["1L"])
setting("Second-line or later", ["second-line", "second line", "2nd line", "later-line", "previously treated", "pretreated", "pre-treated"], ["2L", "2L+"])
setting("Maintenance", ["maintenance therapy", "maintenance treatment"])
setting("Prevention / chemoprevention", ["chemoprevention", "risk reduction", "breast cancer prevention", "prevention of breast cancer"])
setting("Post-neoadjuvant (residual disease)", ["residual disease", "residual invasive disease", "post-neoadjuvant", "non-pcr"])


def population(name, aliases=(), cs=(), context=None):
    return _add("StudyPopulation", "population", name, aliases, cs, (), context)


population("Postmenopausal women", ["postmenopausal", "post-menopausal", "postmenopausal women"])
population("Premenopausal / perimenopausal women", ["premenopausal", "pre-menopausal", "perimenopausal", "pre/perimenopausal", "premenopausal women"])
population("Men", ["male patients", "men with breast cancer", "male or female"])
population("Older adults", ["elderly", "older adults", "older patients", "aged 65", "aged 70", "geriatric"])
population("Asian / Chinese patients", ["chinese patients", "asian patients", "asian women", "chinese women"])

# ---------------------------------------------------------------------------
# Adverse events (CTCAE-aligned). extra label "Symptom" marks patient-experienced symptoms.
# ---------------------------------------------------------------------------
def ae(name, aliases=(), cs=(), symptom=False, context=None):
    return _add("AdverseEvent", "ae", name, aliases, cs, (), context, ["Symptom"] if symptom else [])


ae("Neutropenia", ["neutropenia", "neutrophil count decreased", "decreased neutrophil count"])
ae("Febrile neutropenia", ["febrile neutropenia", "neutropenic fever"], ["FN"], context=r"(febrile|neutropen|G-CSF|filgrastim)")
ae("Anemia", ["anemia", "anaemia", "hemoglobin decreased"])
ae("Thrombocytopenia", ["thrombocytopenia", "platelet count decreased"])
ae("Leukopenia", ["leukopenia", "white blood cell decreased"])
ae("Diarrhea", ["diarrhea", "diarrhoea"], symptom=True)
ae("Nausea", ["nausea"], symptom=True)
ae("Vomiting", ["vomiting", "emesis"], symptom=True)
ae("Fatigue", ["fatigue", "asthenia"], symptom=True)
ae("Alopecia", ["alopecia", "hair loss"])
ae("Peripheral neuropathy", ["peripheral neuropathy", "peripheral sensory neuropathy", "neuropathy", "chemotherapy-induced peripheral neuropathy"], ["CIPN"], symptom=True)
ae("Interstitial lung disease / pneumonitis", ["interstitial lung disease", "pneumonitis", "ild/pneumonitis", "drug-induced ild"], ["ILD"])
ae("Left ventricular dysfunction", ["left ventricular dysfunction", "lvef decrease", "decreased lvef", "lvef decline", "ejection fraction decreased", "left ventricular ejection fraction decreased", "cardiotoxicity", "cardiac toxicity", "cardiac dysfunction"])
ae("Congestive heart failure", ["congestive heart failure", "heart failure"], ["CHF"])
ae("QT prolongation", ["qt prolongation", "qtc prolongation", "qt interval prolonged", "prolonged qtc", "qtcf prolongation"])
ae("Hepatotoxicity", ["hepatotoxicity", "drug-induced liver injury", "liver injury", "hepatic toxicity"], ["DILI"])
ae("ALT/AST increased", ["alt increased", "ast increased", "transaminase elevation", "elevated transaminases", "transaminitis", "aminotransferase increased"])
ae("Hyperbilirubinemia", ["hyperbilirubinemia", "blood bilirubin increased"])
ae("Hyperglycemia", ["hyperglycemia", "hyperglycaemia"])
ae("Rash", ["rash", "maculopapular rash", "skin rash"], symptom=True)
ae("Stomatitis / mucositis", ["stomatitis", "mucositis", "oral mucositis"], symptom=True)
ae("Hand-foot syndrome", ["hand-foot syndrome", "palmar-plantar erythrodysesthesia", "hand foot syndrome", "palmar-plantar erythrodysaesthesia"], ["PPE"])
ae("Infusion-related reaction", ["infusion-related reaction", "infusion related reaction", "infusion reaction"], ["IRR"])
ae("Hypersensitivity reaction", ["hypersensitivity", "anaphylaxis", "allergic reaction"])
ae("Venous thromboembolism", ["venous thromboembolism", "deep vein thrombosis", "pulmonary embolism", "thromboembolic event"], ["VTE", "DVT"])
ae("Hypothyroidism", ["hypothyroidism"])
ae("Hyperthyroidism", ["hyperthyroidism"])
ae("Colitis", ["colitis"])
ae("Immune-mediated hepatitis", ["immune-mediated hepatitis", "autoimmune hepatitis"])
ae("Adrenal insufficiency", ["adrenal insufficiency"])
ae("Immune-related adverse events", ["immune-related adverse event", "immune-mediated adverse event", "immune-related adverse events", "irae"], ["irAE", "imAE"])
ae("Arthralgia", ["arthralgia", "joint pain"], symptom=True)
ae("Myalgia", ["myalgia"], symptom=True)
ae("Hot flashes / vasomotor symptoms", ["hot flashes", "hot flushes", "vasomotor symptoms", "hot flash"], symptom=True)
ae("Osteonecrosis of the jaw", ["osteonecrosis of the jaw"], ["ONJ"])
ae("Hypocalcemia", ["hypocalcemia", "hypocalcaemia"])
ae("Constipation", ["constipation"], symptom=True)
ae("Decreased appetite", ["decreased appetite", "anorexia"], symptom=True)
ae("Dysgeusia", ["dysgeusia", "taste disturbance"], symptom=True)
ae("Peripheral edema", ["peripheral edema", "oedema", "edema"], symptom=True)
ae("Headache", ["headache"], symptom=True)
ae("Insomnia", ["insomnia"], symptom=True)
ae("Dyspnea", ["dyspnea", "dyspnoea", "shortness of breath"], symptom=True)
ae("Cough", ["cough"], symptom=True)
ae("Pain", ["bone pain", "musculoskeletal pain", "pain"], symptom=True)
ae("Myelodysplastic syndrome / AML", ["myelodysplastic syndrome", "acute myeloid leukemia", "acute myeloid leukaemia"], ["MDS", "AML"], context=r"(myelodysplastic|leuk|PARP|olaparib|niraparib|talazoparib|MDS/AML)")
ae("Keratitis / ocular toxicity", ["keratitis", "ocular toxicity", "keratopathy", "dry eye", "blurred vision"])
ae("Embryo-fetal toxicity", ["embryo-fetal toxicity", "embryofetal toxicity", "teratogenic"])
ae("Infection", ["infection", "sepsis", "neutropenic sepsis"])
ae("Endometrial hyperplasia / cancer", ["endometrial hyperplasia", "uterine malignancies"])
ae("Osteoporosis / bone fracture", ["osteoporosis", "bone fracture", "bone loss", "loss of bone mineral density"])
ae("Renal toxicity", ["renal toxicity", "nephrotoxicity", "creatinine increased", "acute kidney injury"])
ae("Hypokalemia", ["hypokalemia", "hypokalaemia"])
ae("Hypomagnesemia", ["hypomagnesemia", "hypomagnesaemia"])
ae("Cataract", ["cataract", "cataracts"])
ae("Photosensitivity", ["photosensitivity"])
ae("Dose-limiting toxicity", ["dose-limiting toxicity", "dose limiting toxicity", "dose-limiting toxicities"], ["DLT", "DLTs"])

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def endpoint(name, aliases=(), cs=(), context=None):
    return _add("Endpoint", "endpoint", name, aliases, cs, (), context)


endpoint("Progression-free survival", ["progression-free survival", "progression free survival"], ["PFS", "rPFS"])
endpoint("Overall survival", ["overall survival"], ["OS"], context=r"(OS rate|median OS|endpoint|survival|months|HR\b|hazard|PFS|DFS|EFS|ORR|pCR|objective|secondary|primary)")
endpoint("Pathological complete response", ["pathological complete response", "pathologic complete response", "pathological complete remission"], ["pCR", "tpCR", "bpCR"])
endpoint("Objective response rate", ["objective response rate", "overall response rate", "objective response", "best overall response", "confirmed objective response rate"], ["ORR", "cORR", "OR"], context=r"(response|RECIST|ORR|CR|PR|rate)")
endpoint("Disease-free survival", ["disease-free survival", "disease free survival"], ["DFS"])
endpoint("Invasive disease-free survival", ["invasive disease-free survival", "invasive disease free survival"], ["IDFS", "iDFS"])
endpoint("Event-free survival", ["event-free survival", "event free survival"], ["EFS"])
endpoint("Distant disease-free survival", ["distant disease-free survival", "distant recurrence-free survival", "distant relapse-free survival"], ["DDFS", "DRFS", "DRFI"])
endpoint("Recurrence-free survival", ["recurrence-free survival", "relapse-free survival", "recurrence-free interval"], ["RFS", "RFI"])
endpoint("Duration of response", ["duration of response", "duration of objective response"], ["DoR", "DOR"])
endpoint("Clinical benefit rate", ["clinical benefit rate", "clinical benefit response"], ["CBR"])
endpoint("Disease control rate", ["disease control rate"], ["DCR"])
endpoint("Time to progression", ["time to progression", "time to disease progression"], ["TTP"])
endpoint("Time to treatment failure", ["time to treatment failure", "time to next treatment", "time to first subsequent therapy"], ["TTF", "TTNT"])
endpoint("PFS2 (second progression)", ["second progression-free survival", "progression-free survival 2", "time to second progression"], ["PFS2"])
endpoint("Residual cancer burden", ["residual cancer burden"], ["RCB"])
endpoint("Clinical response (neoadjuvant)", ["clinical response rate", "clinical objective response", "radiological response"])
endpoint("CNS / intracranial response", ["intracranial response", "cns objective response", "cns response rate", "intracranial objective response rate"], ["CNS-ORR", "IC-ORR"])
endpoint("Ki-67 change (biological response)", ["change in ki-67", "ki-67 suppression", "ki67 suppression", "change in ki67", "complete cell cycle arrest"], ["CCCA"])
endpoint("Safety and tolerability", ["safety and tolerability", "incidence of adverse events", "incidence of treatment-emergent adverse events", "frequency of adverse events", "treatment-emergent adverse events"], ["TEAE", "TEAEs"])
endpoint("Maximum tolerated dose / RP2D", ["maximum tolerated dose", "recommended phase 2 dose", "recommended phase ii dose"], ["MTD", "RP2D"])
endpoint("Pharmacokinetic parameters", ["pharmacokinetic parameters", "pharmacokinetics", "area under the concentration-time curve", "maximum plasma concentration", "trough concentration"], ["Cmax", "Ctrough", "AUC0-inf", "AUCtau"])
endpoint("Patient-reported outcomes / quality of life", ["patient-reported outcomes", "quality of life", "health-related quality of life", "eortc qlq-c30", "qlq-br23", "qlq-br45", "fact-b", "eq-5d-5l", "eq-5d"], ["PROs", "PRO", "HRQoL", "QoL"])
endpoint("Time to deterioration", ["time to deterioration", "time to definitive deterioration", "time to confirmed deterioration"], ["TTD"])
endpoint("Breast cancer-free interval", ["breast cancer-free interval", "breast cancer free interval"], ["BCFI"])
endpoint("Immunogenicity (anti-drug antibodies)", ["anti-drug antibodies", "anti-drug antibody", "immunogenicity"], ["ADA", "ADAs"])
endpoint("Feasibility", ["feasibility"])
endpoint("Incidence of invasive breast cancer", ["incidence of invasive breast cancer", "breast cancer incidence"])

# ---------------------------------------------------------------------------
# Routes, assessments, designs, phases, statistical methods
# ---------------------------------------------------------------------------
for nm, al, cs in [("Intravenous", ["intravenous", "intravenously", "iv infusion", "i.v."], ["IV"]),
                   ("Oral", ["orally", "oral administration", "by mouth", "p.o."], ["PO"]),
                   ("Subcutaneous", ["subcutaneous", "subcutaneously", "s.c."], ["SC", "SQ"]),
                   ("Intramuscular", ["intramuscular", "intramuscularly", "i.m."], ["IM"]),
                   ("Topical / transdermal", ["topical", "transdermal", "topically"], []),
                   ("Intrathecal", ["intrathecal", "intrathecally"], []),
                   ("Hepatic intra-arterial", ["hepatic arterial infusion", "intra-arterial", "intra-hepatic", "intrahepatic arterial"], ["HAI"])]:
    _add("RouteOfAdministration", "route", nm, al, cs, context=r"(mg|dose|infusion|administ|given|tablet|capsule|daily|day|q\dw|every)" if cs else None)

for nm, al, cs, kind in [
    ("Electrocardiogram", ["electrocardiogram", "12-lead ecg", "12-lead electrocardiogram"], ["ECG", "EKG"], "DiagnosticProcedure"),
    ("Echocardiogram / MUGA (LVEF assessment)", ["echocardiogram", "multigated acquisition", "muga scan", "lvef assessment", "left ventricular ejection fraction"], ["ECHO", "MUGA", "LVEF"], "DiagnosticProcedure"),
    ("CT scan", ["computed tomography", "ct scan", "ct scans", "ct of the chest", "ct/mri", "high-resolution ct"], ["CT", "HRCT"], "DiagnosticProcedure"),
    ("MRI", ["magnetic resonance imaging", "mri scan", "brain mri", "breast mri"], ["MRI"], "DiagnosticProcedure"),
    ("Bone scan", ["bone scan", "bone scintigraphy", "radionuclide bone scan"], [], "DiagnosticProcedure"),
    ("PET/CT", ["positron emission tomography", "fdg-pet", "pet/ct", "pet-ct", "pet scan"], ["PET"], "DiagnosticProcedure"),
    ("Mammography / breast imaging", ["mammogram", "mammography", "breast ultrasound"], [], "DiagnosticProcedure"),
    ("Tumor biopsy", ["tumor biopsy", "tumour biopsy", "core needle biopsy", "core biopsy", "archival tumor tissue", "fresh biopsy", "tissue biopsy"], [], "DiagnosticProcedure"),
    ("Tumor response assessment (RECIST)", ["recist 1.1", "recist v1.1", "recist version 1.1", "tumor assessment", "tumour assessment", "rano-bm"], ["RECIST"], "Assessment"),
    ("ECOG performance status", ["eastern cooperative oncology group", "ecog performance status", "performance status", "karnofsky"], ["ECOG", "KPS"], "Assessment"),
    ("Physical examination", ["physical examination", "physical exam"], [], "Assessment"),
    ("Vital signs", ["vital signs"], [], "Assessment"),
    ("Hematology (complete blood count)", ["complete blood count", "hematology", "haematology", "full blood count"], ["CBC"], "LaboratoryTest"),
    ("Serum chemistry", ["serum chemistry", "clinical chemistry", "blood chemistry", "comprehensive metabolic panel"], ["CMP"], "LaboratoryTest"),
    ("Liver function tests", ["liver function tests", "liver function test", "hepatic function panel"], ["LFTs", "LFT"], "LaboratoryTest"),
    ("Renal function / creatinine clearance", ["creatinine clearance", "renal function", "serum creatinine", "egfr calculation"], ["CrCl"], "LaboratoryTest"),
    ("Coagulation tests", ["coagulation", "prothrombin time", "international normalized ratio"], ["INR", "aPTT"], "LaboratoryTest"),
    ("Urinalysis", ["urinalysis"], [], "LaboratoryTest"),
    ("Pregnancy test", ["pregnancy test", "serum pregnancy", "urine pregnancy", "beta-hcg"], [], "LaboratoryTest"),
    ("Thyroid function tests", ["thyroid function", "thyroid-stimulating hormone"], ["TSH"], "LaboratoryTest"),
    ("Glucose / HbA1c", ["fasting glucose", "fasting plasma glucose", "hba1c", "glycated hemoglobin", "glycosylated hemoglobin"], ["FPG"], "LaboratoryTest"),
    ("Lipid panel", ["lipid panel", "fasting lipids", "lipid profile"], [], "LaboratoryTest"),
    ("Hepatitis B/C and HIV serology", ["hepatitis b", "hepatitis c", "hbsag", "hcv antibody", "hiv test", "hiv serology"], [], "LaboratoryTest"),
    ("Pharmacokinetic sampling", ["pharmacokinetic sampling", "pk sampling", "pk samples", "pharmacokinetic samples"], [], "Assessment"),
    ("Ophthalmologic examination", ["ophthalmologic examination", "ophthalmological examination", "eye examination", "slit lamp"], [], "Assessment"),
    ("Pulmonary function test", ["pulmonary function test", "spirometry", "dlco"], ["PFT"], "DiagnosticProcedure"),
    ("Bone mineral density (DXA)", ["bone mineral density", "dxa scan", "dexa scan", "dual-energy x-ray absorptiometry"], ["BMD", "DXA", "DEXA"], "DiagnosticProcedure"),
    ("Quality-of-life questionnaire", ["qlq-c30", "fact-b questionnaire", "eq-5d questionnaire", "pro questionnaire"], [], "Assessment"),
    ("Blood sample for ctDNA", ["ctdna sample", "plasma sample for ctdna", "blood sample for ctdna", "liquid biopsy sample"], [], "Assessment"),
]:
    ctx = r"(scan|test|assess|perform|screen|baseline|cycle|day|every|week|visit|evaluat|measure|sample|obtain|required)" if cs else None
    _add(kind, "assessment", nm, al, cs, context=ctx)

for nm, al, cs in [("Randomized", ["randomized", "randomised", "randomization"], []),
                   ("Double-blind", ["double-blind", "double blind", "double-blinded"], []),
                   ("Open-label", ["open-label", "open label"], []),
                   ("Placebo-controlled", ["placebo-controlled", "placebo controlled"], []),
                   ("Single-arm", ["single-arm", "single arm", "single-group"], []),
                   ("Multicenter", ["multicenter", "multi-center", "multicentre", "multi-centre", "multinational", "multi-institutional"], []),
                   ("Non-inferiority", ["non-inferiority", "noninferiority"], []),
                   ("Dose escalation / expansion", ["dose escalation", "dose-escalation", "dose expansion", "3+3 design", "dose-finding"], []),
                   ("Crossover", ["crossover design", "cross-over design", "crossover study"], []),
                   ("Window-of-opportunity", ["window of opportunity", "window-of-opportunity"], []),
                   ("Basket / pan-tumor", ["basket study", "basket trial", "pan-tumor", "pantumor", "tumor-agnostic"], []),
                   ("Adaptive / platform", ["adaptive design", "platform trial", "adaptively randomized"], []),
                   ("Pilot / feasibility", ["pilot study", "feasibility study", "pilot trial"], []),
                   ("Superiority", ["superiority"], [])]:
    _add("StudyDesign", "design", nm, al, cs)

for nm in ["Phase 1", "Phase 1b", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4", "Pilot"]:
    _add("StudyPhase", "phase", nm, [])

for nm, al, cs in [("Kaplan-Meier method", ["kaplan-meier", "kaplan meier"], []),
                   ("Cox proportional hazards model", ["cox proportional hazards", "cox regression", "cox proportional hazard", "cox model"], []),
                   ("Stratified log-rank test", ["stratified log-rank", "stratified log rank"], []),
                   ("Log-rank test", ["log-rank test", "log rank test", "logrank"], []),
                   ("Cochran-Mantel-Haenszel test", ["cochran-mantel-haenszel", "mantel-haenszel", "cmh test"], ["CMH"]),
                   ("Logistic regression", ["logistic regression"], []),
                   ("Mixed model for repeated measures", ["mixed model for repeated measures", "mixed-effect model repeated measure", "mixed effects model"], ["MMRM"]),
                   ("O'Brien-Fleming boundary", ["o'brien-fleming", "obrien-fleming", "lan-demets", "lan demets"], []),
                   ("Clopper-Pearson exact confidence interval", ["clopper-pearson", "clopper pearson", "exact binomial"], []),
                   ("Simon two-stage design", ["simon two-stage", "simon's two-stage", "simon 2-stage", "two-stage design", "optimal two-stage"], []),
                   ("Brookmeyer-Crowley method", ["brookmeyer-crowley", "brookmeyer and crowley"], []),
                   ("Fine-Gray competing risks", ["fine-gray", "fine and gray", "competing risk"], []),
                   ("Bayesian analysis", ["bayesian"], []),
                   ("Fisher's exact test", ["fisher's exact", "fisher exact"], []),
                   ("Chi-square test", ["chi-square", "chi-squared"], []),
                   ("Wilcoxon / Mann-Whitney test", ["wilcoxon", "mann-whitney"], []),
                   ("Intention-to-treat analysis", ["intention-to-treat", "intent-to-treat", "full analysis set"], ["ITT", "FAS"])]:
    _add("StatisticalMethod", "stat", nm, al, cs)

# ---------------------------------------------------------------------------
BY_ID: dict[str, Concept] = {c.id: c for c in CONCEPTS}

# Nomenclature suffixes that identify a drug-like term absent from the dictionary
DRUG_SUFFIX = re.compile(
    r"\b([a-z]{3,}(?:mab|zumab|ximab|umab|tinib|ciclib|lisib|parib|tecan|platin|rubicin|taxel|strant|lukast|"
    r"sertib|limus|vedotin|deruxtecan|emtansine|gestrant|ifene|rozole|relin|degib|rafenib))\b", re.I)
# Development codes (e.g. "LY2157299", "MK-3475", "GDC-0077", "HD201")
DRUG_CODE = re.compile(r"\b((?:[A-Z]{2,5}[- ]?\d{3,7}[a-z]?)|(?:[A-Z]\d[A-Z]{1,3}-?\d{3,6}))\b")
DRUG_CODE_STOP = re.compile(r"^(NCT|ISO|ICH|GCP|CTCAE|IND|IRB|ECOG|RECIST|PMID|DOI|EUDRACT|CFR|IEC|SAP|CRF|ID|NO|USA|EU|COVID|SARS|ICD|CT|MR|ASCO|CAP|NCI|FDA|EMA|WHO|AJCC|ESMO|TNM|BIRADS|NSABP|SWOG|ECOG|ALLIANCE|CALGB|NRG|RTOG|IBCSG|CCTG|EORTC|AZ|MSD|BMS|GSK|SOP|USP|BMI|HIV|HBV|HCV|PDF|EDC|IWRS|IVRS|IXRS|FAX|TEL|CA|PO|FL|MD|NJ|NY|TX|IL|MA|PA|EC|LVEF|QTCF|QTC|PT|SOC|AE|SAE|DLT|AUC|CYP|CYP3A|UGT|OATP|BCRP|ABCB|ABCG|HLA)", re.I)
