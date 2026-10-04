"""Shared constants. Single source of truth for both lanes (changes need a contract PR)."""

CONTRACT_VERSION = "0.1.0"

TYPE_FONDATION = "fondation"
TYPE_POUTRE = "poutre"
TYPE_MUR = "mur_refend"
TYPE_COLONNE = "colonne"
TYPE_DALLE = "dalle"
ELEMENT_TYPES = (TYPE_FONDATION, TYPE_POUTRE, TYPE_MUR, TYPE_COLONNE, TYPE_DALLE)

SOURCE_PLAN = "plan"
SOURCE_SHOP = "shop"

STATUS_COMPLIANT = "compliant"
STATUS_NON_COMPLIANT = "non_compliant"
STATUS_MISSING = "missing"
STATUS_ADDED = "added"
STATUS_NEEDS_REVIEW = "needs_review"
STATUSES = (
    STATUS_COMPLIANT,
    STATUS_NON_COMPLIANT,
    STATUS_MISSING,
    STATUS_ADDED,
    STATUS_NEEDS_REVIEW,
)

CHECK_TYPES = (
    "cross.plan_vs_shop",
    "cross.shop_vs_shop",
    "cross.plan_vs_plan",
    "cross.revision",
    "cross.project",
    "self.peer_outlier",
    "self.level_consistency",
    "self.internal_consistency",
    "self.plausibility",
    "self.duplicate",
)

BAR_SIZES = ("10M", "15M", "20M", "25M", "30M", "35M")

INCH_MM = 25.4
FOOT_MM = 304.8

# Comparison tolerances
SPACING_TOL_MM = 1.0
LENGTH_TOL_MM = 5.0

# Quality weights (shared/constants.py is the one place to tune them)
OCR_SNAP_PENALTY = 0.9
DERIVED_PENALTY = 0.8
LOOSE_PATTERN_FACTOR = 0.8
CONSISTENCY_FAIL_FACTOR = 0.85
CONSISTENCY_FLOOR = 0.3
ANCHOR_FACTOR = {"outline": 1.0, "label": 0.95, "mark_axis": 0.8, "text_only": 0.5}

# Internal consistency: tie count x spacing / storey height. The accepted band is learned from the
# project's own shop elements (median +/- K robust sigmas); the fixed band is only a fallback
# when there are too few samples.
TIE_RATIO_MIN = 0.8
TIE_RATIO_MAX = 1.3
TIE_BAND_K = 6.0
TIE_BAND_SIGMA_FLOOR = 0.05  # of the median, so a very uniform project does not get a zero band
TIE_BAND_MIN_SAMPLES = 20

# Peer outlier detection
PEER_MIN_GROUP = 8
PEER_MODE_SHARE_MIN = 0.6
PEER_RARE_SHARE_MAX = 0.1

# Finding status thresholds
TRUST_MIN_FOR_VERDICT = 0.7
ANOMALY_ESCALATE = 0.8
PAIR_PROB_ESCALATE = 0.6

# Canonical level names
LEVEL_SS = "SS"
LEVEL_RDC = "RDC"
LEVEL_TOIT = "TOIT"

# Output file names inside a metadata directory
FILE_MANIFEST = "manifest.json"
FILE_ELEMENTS_STRICT = "elements.json"
FILE_ELEMENTS_EXT = "elements.ext.json"
FILE_GRID = "grid.json"
FILE_LEVELS = "levels.json"
FILE_SHEETS = "sheets.json"
FILE_IDS = "ids.json"
