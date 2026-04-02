"""
SmartDocX — Extraction Engine v2
Strong multi-strategy extraction with OCR correction, confidence scoring,
contextual fallbacks, and per-document-type field validation.
"""
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# SECTION 1 — TEXT PREPROCESSING & OCR REPAIR
# ─────────────────────────────────────────────

# Common OCR single-char confusions: (wrong, correct, context)
_OCR_CHAR_MAP = [
    (r"(?<=\d)O(?=\d)", "0"),   # O → 0 between digits
    (r"(?<=\d)[Il](?=\d)", "1"),# I/l → 1 between digits
    (r"(?<=\d)S(?=\d)", "5"),   # S → 5 between digits
    (r"(?<=\d)B(?=\d)", "8"),   # B → 8 between digits
    (r"(?<=\d)G(?=\d)", "6"),   # G → 6 between digits
    # NOTE: Z→2 intentionally removed — Z is a valid char in GSTIN (position 13)
    (r"\bI(?=\d{4,})", "1"),    # leading I before long digit run
]

# Known label aliases for robust field matching
_LABEL_ALIASES = {
    "name": ["NAME", "FULL NAME", "HOLDER NAME", "APPLICANT NAME",
             "CARD HOLDER", "ACCOUNT HOLDER", "PROPRIETOR"],
    "father": ["FATHER", "FATHER'S NAME", "S/O", "SON OF", "D/O", "DAUGHTER OF", "C/O"],
    "dob":    ["DOB", "DATE OF BIRTH", "BIRTH DATE", "D.O.B", "DATE OF BIRTH"],
    "address":["ADDRESS", "ADDR", "PERMANENT ADDRESS", "RESIDENTIAL ADDRESS",
               "PRINCIPAL PLACE OF BUSINESS", "PLACE OF BUSINESS"],
    "phone":  ["PHONE", "MOBILE", "CONTACT", "MOB", "TEL", "TELEPHONE"],
    "email":  ["EMAIL", "E-MAIL", "EMAIL ID", "MAIL"],
    "gender": ["GENDER", "SEX"],
    "valid":  ["VALID UPTO", "VALID TO", "VALIDITY", "EXPIRY", "EXPIRY DATE",
               "VALID TILL", "VALID UP TO"],
}


def preprocess_text(raw: str) -> str:
    """
    Deep OCR cleanup:
    1. Normalize whitespace/control chars
    2. Uppercase
    3. Fix common OCR character confusions in numeric/ID contexts
    4. Collapse repeated punctuation
    """
    if not raw:
        return ""
    text = raw
    text = re.sub(r"[\r\t\f\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.upper()
    for pattern, replacement in _OCR_CHAR_MAP:
        text = re.sub(pattern, replacement, text)
    # Collapse repeated dashes/dots that OCR sometimes produces
    text = re.sub(r"[-]{3,}", "-", text)
    text = re.sub(r"[.]{3,}", ".", text)
    return text


def normalize_date(date_str: str) -> str:
    """Try many date formats and return ISO YYYY-MM-DD, else original."""
    if not date_str:
        return date_str
    s = date_str.strip()
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%d %b %Y", "%d %B %Y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d/%m/%y", "%d-%m-%y",
        "%b %d, %Y", "%B %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return s


def clean_name(raw: str) -> str:
    """Remove noise tokens from extracted names."""
    if not raw:
        return raw
    # Strip trailing noise words
    noise = r"\b(INDIA|GOVT|GOVERNMENT|DEPARTMENT|OF|THE|AND|PVT|LTD|LIMITED)\s*$"
    name = re.sub(noise, "", raw.strip(), flags=re.IGNORECASE).strip(" ,.-")
    # Collapse multiple spaces
    name = re.sub(r"\s{2,}", " ", name)
    return name


def extract_after_label(text: str, labels: list, max_len: int = 60) -> str:
    """
    Context-aware extraction: find any label from the list and grab
    the value that follows it, stopping at the next label or newline.
    Returns the best (longest non-noise) match.
    """
    # Build a stop pattern — stop at any known label keyword
    stop_words = (
        r"(?:NAME|FATHER|DOB|DATE|ADDRESS|PHONE|MOBILE|EMAIL|GENDER|VALID|"
        r"GSTIN|PAN|AADHAAR|UDYAM|FSSAI|DL|RC|CHASSIS|ENGINE|OWNER|"
        r"CONSTITUTION|TAXPAYER|CATEGORY|TYPE|DISTRICT|STATE|PINCODE|"
        r"NOTARY|SUBJECT|PARTY|CLAUSE|JURISDICTION|DEPONENT|AGE|RESIDING)"
    )
    candidates = []
    for label in labels:
        pat = (
            re.escape(label)
            + r"[\s:.\-]*"
            + r"([A-Z0-9][A-Z0-9\s,./\-]{1," + str(max_len) + r"}?)"
            + r"(?=\s*(?:" + stop_words + r")|\n|$)"
        )
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = m.group(1).strip(" ,.-\n")
            if len(val) >= 2:
                candidates.append(val)
    if not candidates:
        return ""
    return max(candidates, key=len)


def score_extraction(extracted: dict, required_fields: list) -> float:
    """
    Compute a 0-100 confidence score based on:
    - How many required fields were found
    - Whether key ID fields match expected format
    """
    if not required_fields:
        return 50.0
    found = sum(1 for f in required_fields if extracted.get(f))
    base = (found / len(required_fields)) * 100
    return round(min(base, 100.0), 1)


# ─────────────────────────────────────────────
# SECTION 2 — DOCUMENT TYPE DETECTION
# ─────────────────────────────────────────────

# Each entry: (doc_type, [(pattern_or_keyword, weight), ...])
# Detection picks the type with highest cumulative weight.
_DETECTION_RULES = {
    "PAN": [
        (r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", 10),          # PAN number format
        (r"INCOME\s*TAX\s*DEPARTMENT", 8),
        (r"PERMANENT\s*ACCOUNT\s*NUMBER", 10),
        (r"\bPAN\b", 3),
        (r"GOVT\.\s*OF\s*INDIA", 2),
    ],
    "AADHAAR": [
        (r"\b\d{4}\s?\d{4}\s?\d{4}\b", 8),            # 12-digit aadhaar
        (r"UNIQUE\s*IDENTIFICATION\s*AUTHORITY", 10),
        (r"\bUIDAI\b", 10),
        (r"\bAADHAAR\b", 8),
        (r"ENROLMENT\s*NO", 4),
        (r"VID\s*:", 3),
    ],
    "GST": [
        (r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z0-9]Z[A-Z0-9]\b", 10),
        (r"\bGSTIN\b", 10),
        (r"GOODS\s*AND\s*SERVICES\s*TAX", 8),
        (r"\bGST\b", 3),
        (r"CENTRAL\s*TAX", 3),
    ],
    "FSSAI": [
        (r"\b\d{14}\b", 6),
        (r"\bFSSAI\b", 10),
        (r"FOOD\s*SAFETY", 8),
        (r"FOOD\s*BUSINESS\s*OPERATOR", 8),
        (r"LICENSE\s*NO", 3),
    ],
    "UDYAM": [
        (r"\bUDYAM-[A-Z]{2}-\d{2}-\d{7}\b", 10),
        (r"UDYAM\s*REGISTRATION", 10),
        (r"\bMSME\b", 5),
        (r"MINISTRY\s*OF\s*MICRO", 6),
    ],
    "DL": [
        (r"\bDRIVING\s*LICEN[CS]E\b", 10),
        (r"\bDRIVING\s*LICENCE\b", 10),
        (r"\bDL\s*NO\b", 8),
        (r"\bDL[-\s]?\d", 6),
        (r"TRANSPORT\s*DEPARTMENT", 4),
        (r"\bRTO\b", 3),
        (r"MOTOR\s*VEHICLE", 4),
    ],
    "RC": [
        (r"REGISTRATION\s*CERTIFICATE", 10),
        (r"\bRC\s*NO\b", 8),
        (r"VEHICLE\s*REGISTRATION", 8),
        (r"CHASSIS\s*NO", 5),
        (r"ENGINE\s*NO", 5),
        (r"REGISTERED\s*OWNER", 6),
    ],
    "RESUME": [
        (r"\bRESUME\b", 10),
        (r"CURRICULUM\s*VITAE", 10),
        (r"\bCV\b", 5),
        (r"\bOBJECTIVE\b", 4),
        (r"\bSKILLS?\b", 3),
        (r"\bEXPERIENCE\b", 3),
        (r"\bEDUCATION\b", 3),
        (r"\bPROJECTS?\b", 2),
    ],
    "AGREEMENT": [
        (r"\bAGREEMENT\b", 8),
        (r"\bTHIS\s*AGREEMENT\b", 10),
        (r"\bPARTIES\b", 4),
        (r"\bFIRST\s*PARTY\b", 6),
        (r"\bSECOND\s*PARTY\b", 6),
        (r"\bWHEREAS\b", 5),
        (r"\bHEREINAFTER\b", 6),
    ],
    "AFFIDAVIT": [
        (r"\bAFFIDAVIT\b", 10),
        (r"SOLEMNLY\s*AFFIRM", 10),
        (r"SOLEMNLY\s*SWEAR", 10),
        (r"\bDEPONENT\b", 8),
        (r"\bNOTARY\b", 5),
        (r"\bOATH\b", 4),
    ],
}


def detect_doc_types(text: str) -> list:
    """
    Score-based detection. Returns list of (doc_type, score) sorted by score desc.
    Only returns types that exceed a minimum threshold.
    """
    processed = preprocess_text(text)
    scores = {}
    for doc_type, rules in _DETECTION_RULES.items():
        total = 0
        for pattern, weight in rules:
            if re.search(pattern, processed, re.IGNORECASE):
                total += weight
        if total >= 6:  # minimum threshold to avoid false positives
            scores[doc_type] = total

    # Sort by score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [dt for dt, _ in ranked]


# ─────────────────────────────────────────────
# SECTION 3 — PAN EXTRACTOR
# ─────────────────────────────────────────────

def extract_pan(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # PAN Number — strict format AAAAA9999A, allow 1-2 spaces from OCR
    pan_match = re.search(r"\b([A-Z]{5}[\s]?\d{4}[\s]?[A-Z])\b", t)
    if pan_match:
        result["PAN Number"] = pan_match.group(1).replace(" ", "")

    # Name — try label-based first, then positional on original text lines
    name = extract_after_label(t, ["NAME", "FULL NAME", "CARD HOLDER"])
    if not name:
        raw_lines = [l.strip().upper() for l in text.splitlines() if l.strip()]
        for i, line in enumerate(raw_lines):
            if re.search(r"\bINCOME\s*TAX\b|\bGOVT\b|\bPERMANENT\s*ACCOUNT\b", line):
                if i + 2 < len(raw_lines):
                    candidate = raw_lines[i + 2]
                    if re.match(r"^[A-Z\s.]{3,40}$", candidate) and not re.search(r"\d", candidate):
                        name = candidate
                        break
    result["Name"] = clean_name(name) if name else ""

    # Father's Name
    father = extract_after_label(t, ["FATHER'S NAME", "FATHER NAME", "S/O", "SON OF", "D/O"])
    if not father:
        # Try: line after name that looks like a name
        lines = [l.strip() for l in t.splitlines() if l.strip()]
        name_val = result.get("Name", "")
        for i, line in enumerate(lines):
            if name_val and name_val in line and i + 1 < len(lines):
                nxt = lines[i + 1]
                if re.match(r"^[A-Z\s.]{3,40}$", nxt) and nxt != name_val:
                    father = nxt
                    break
    result["Father's Name"] = clean_name(father) if father else ""

    # Date of Birth — multiple formats
    dob = ""
    dob_match = re.search(
        r"(?:DOB|DATE\s*OF\s*BIRTH|BIRTH\s*DATE|D\.O\.B)[:\s.\-]*"
        r"((?:\d{2}[/.\-]\d{2}[/.\-]\d{4})|(?:\d{2}\s+[A-Z]{3}\s+\d{4}))",
        t, re.IGNORECASE
    )
    if dob_match:
        dob = normalize_date(dob_match.group(1))
    else:
        # Fallback: any date-like pattern on the card
        dates = re.findall(r"\b(\d{2}[/.\-]\d{2}[/.\-]\d{4})\b", t)
        if dates:
            dob = normalize_date(dates[0])
    result["Date of Birth"] = dob

    required = ["PAN Number", "Name", "Date of Birth"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 4 — AADHAAR EXTRACTOR
# ─────────────────────────────────────────────

def extract_aadhaar(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # Aadhaar Number — 12 digits, may have spaces every 4
    aadhaar_match = re.search(r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b", t)
    if aadhaar_match:
        result["Aadhaar Number"] = aadhaar_match.group(1).replace(" ", "").replace("-", "")
        # Format as XXXX XXXX XXXX
        num = result["Aadhaar Number"]
        if len(num) == 12:
            result["Aadhaar Number"] = f"{num[:4]} {num[4:8]} {num[8:]}"

    # VID (Virtual ID) — 16 digits
    vid = re.search(r"\bVID\s*[:\-]?\s*(\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4})\b", t)
    if vid:
        result["VID"] = vid.group(1).replace(" ", "")

    # Name — label-based first, then positional on ORIGINAL text lines
    name = extract_after_label(t, ["NAME", "FULL NAME"])
    if not name:
        skip_kw = {
            "INDIA", "UIDAI", "AADHAAR", "UNIQUE", "AUTHORITY",
            "GOVERNMENT", "IDENTIFICATION", "ENROLMENT", "MALE",
            "FEMALE", "TRANSGENDER", "ADDRESS", "DOB", "DATE",
            "BIRTH", "VID", "DOWNLOAD", "RESIDENT"
        }
        raw_lines = [l.strip().upper() for l in text.splitlines() if l.strip()]
        for line in raw_lines:
            words = line.split()
            if (2 <= len(words) <= 5
                    and re.match(r"^[A-Z][A-Z\s.]{2,35}$", line)
                    and not any(kw in line for kw in skip_kw)
                    and not re.search(r"\d", line)):
                name = line
                break
    result["Name"] = clean_name(name) if name else ""

    # Date of Birth / Year of Birth
    dob_match = re.search(
        r"(?:DOB|DATE\s*OF\s*BIRTH|BIRTH|YEAR\s*OF\s*BIRTH|YOB)[:\s.\-]*"
        r"((?:\d{2}[/.\-]\d{2}[/.\-]\d{4})|(?:\d{4})|(?:\d{2}\s+[A-Z]{3}\s+\d{4}))",
        t, re.IGNORECASE
    )
    if dob_match:
        result["Date of Birth"] = normalize_date(dob_match.group(1))

    # Gender
    gender_match = re.search(r"\b(MALE|FEMALE|TRANSGENDER)\b", t)
    if gender_match:
        result["Gender"] = gender_match.group(1).capitalize()

    # Address — everything after "ADDRESS" until the Aadhaar number line
    addr_match = re.search(
        r"(?:ADDRESS|ADDR)[:\s]*([A-Z0-9][A-Z0-9\s,./\-]{10,200}?)(?=\d{4}\s?\d{4}\s?\d{4}|$)",
        t, re.DOTALL
    )
    if addr_match:
        addr = re.sub(r"\s+", " ", addr_match.group(1)).strip(" ,")
        result["Address"] = addr[:200]

    # Pincode from address
    pin = re.search(r"\b([1-9]\d{5})\b", t)
    if pin:
        result["Pincode"] = pin.group(1)

    required = ["Aadhaar Number", "Name", "Date of Birth", "Gender"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 5 — GST EXTRACTOR
# ─────────────────────────────────────────────

def extract_gst(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # GSTIN — 15 chars: 2 digits + 5 letters + 4 digits + 1 letter + 1 digit + Z + 1 alphanumeric
    gstin = re.search(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d{1}Z[A-Z0-9])", t)
    if gstin:
        result["GST Number"] = gstin.group(1)
        # Derive state code
        state_code = gstin.group(1)[:2]
        result["State Code"] = state_code

    # Legal Name
    legal = extract_after_label(t, ["LEGAL NAME", "LEGAL NAME OF BUSINESS", "TRADE NAME"])
    if legal:
        result["Legal Name"] = clean_name(legal)

    # Trade Name (separate from legal)
    trade = extract_after_label(t, ["TRADE NAME"])
    if trade and trade != result.get("Legal Name"):
        result["Trade Name"] = clean_name(trade)

    # Date of Registration
    reg_date = re.search(
        r"(?:DATE\s*OF\s*REGISTRATION|REGISTRATION\s*DATE|EFFECTIVE\s*DATE)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if reg_date:
        result["Date of Registration"] = normalize_date(reg_date.group(1))

    # Constitution of Business
    constitution = re.search(
        r"CONSTITUTION\s*OF\s*BUSINESS[:\s]*([A-Z\s/]{3,40}?)(?:\n|$|GSTIN|DATE)",
        t
    )
    if constitution:
        result["Constitution"] = constitution.group(1).strip()

    # Address
    addr = extract_after_label(t, [
        "PRINCIPAL PLACE OF BUSINESS", "PLACE OF BUSINESS", "ADDRESS"
    ], max_len=150)
    if addr:
        result["Address"] = addr[:200]

    # Email
    email = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", t)
    if email:
        result["Email"] = email.group(0).lower()

    # Phone
    phone = re.search(r"\b([6-9]\d{9})\b", t)
    if phone:
        result["Phone"] = phone.group(1)

    # Taxpayer Type
    tp_type = re.search(
        r"(?:TAXPAYER\s*TYPE|TYPE\s*OF\s*TAXPAYER)[:\s]*([A-Z\s]{3,30}?)(?:\n|$)",
        t
    )
    if tp_type:
        result["Taxpayer Type"] = tp_type.group(1).strip()

    required = ["GST Number", "Legal Name", "Date of Registration"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 6 — FSSAI EXTRACTOR
# ─────────────────────────────────────────────

def extract_fssai(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # FSSAI License Number — 14 digits
    lic = re.search(r"\b(\d{14})\b", t)
    if lic:
        result["FSSAI Number"] = lic.group(1)

    # Business / FBO Name
    biz = extract_after_label(t, [
        "NAME OF FOOD BUSINESS OPERATOR", "BUSINESS NAME",
        "FBO NAME", "NAME OF FBO", "COMPANY NAME", "FIRM NAME"
    ])
    if biz:
        result["Business Name"] = clean_name(biz)

    # Address
    addr = extract_after_label(t, ["ADDRESS", "BUSINESS ADDRESS"], max_len=150)
    if addr:
        result["Address"] = addr[:200]

    # Validity / Expiry
    valid = re.search(
        r"(?:VALID\s*UPTO|VALID\s*UP\s*TO|VALIDITY|EXPIRY\s*DATE|VALID\s*TILL)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if valid:
        result["Valid Upto"] = normalize_date(valid.group(1))

    # Issue Date
    issue = re.search(
        r"(?:ISSUE\s*DATE|DATE\s*OF\s*ISSUE|ISSUED\s*ON)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if issue:
        result["Issue Date"] = normalize_date(issue.group(1))

    # Kind of Business
    kind = re.search(
        r"(?:KIND\s*OF\s*BUSINESS|TYPE\s*OF\s*BUSINESS|CATEGORY)[:\s]*([A-Z\s/,]{3,50}?)(?:\n|$)",
        t
    )
    if kind:
        result["Kind of Business"] = kind.group(1).strip()

    # Email & Phone
    email = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", t)
    if email:
        result["Email"] = email.group(0).lower()
    phone = re.search(r"\b([6-9]\d{9})\b", t)
    if phone:
        result["Phone"] = phone.group(1)

    required = ["FSSAI Number", "Business Name", "Valid Upto"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 7 — UDYAM EXTRACTOR
# ─────────────────────────────────────────────

def extract_udyam(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # Udyam Registration Number
    udyam = re.search(r"\b(UDYAM-[A-Z]{2}-\d{2}-\d{7})\b", t)
    if udyam:
        result["Udyam Number"] = udyam.group(1)

    # Enterprise Name
    ent = extract_after_label(t, [
        "NAME OF ENTERPRISE", "ENTERPRISE NAME", "NAME OF UNIT",
        "NAME OF BUSINESS", "BUSINESS NAME"
    ])
    if ent:
        result["Enterprise Name"] = clean_name(ent)

    # Owner / Proprietor
    owner = extract_after_label(t, [
        "NAME OF OWNER", "PROPRIETOR", "OWNER NAME",
        "NAME OF ENTREPRENEUR", "ENTREPRENEUR NAME"
    ])
    if owner:
        result["Owner Name"] = clean_name(owner)

    # Type of Enterprise
    etype = re.search(
        r"(?:TYPE\s*OF\s*ENTERPRISE|ENTERPRISE\s*TYPE|CATEGORY)[:\s]*"
        r"(MICRO|SMALL|MEDIUM)",
        t
    )
    if etype:
        result["Type of Enterprise"] = etype.group(1).capitalize()

    # Major Activity
    activity = re.search(
        r"(?:MAJOR\s*ACTIVITY|ACTIVITY)[:\s]*([A-Z\s/]{3,40}?)(?:\n|$)",
        t
    )
    if activity:
        result["Major Activity"] = activity.group(1).strip()

    # NIC Code
    nic = re.search(r"(?:NIC\s*CODE|NIC)[:\s]*(\d{4,5})", t)
    if nic:
        result["NIC Code"] = nic.group(1)

    # Date of Incorporation / Commencement
    inc_date = re.search(
        r"(?:DATE\s*OF\s*INCORPORATION|DATE\s*OF\s*COMMENCEMENT|COMMENCEMENT\s*DATE)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if inc_date:
        result["Date of Incorporation"] = normalize_date(inc_date.group(1))

    # Address
    addr = extract_after_label(t, ["ADDRESS", "OFFICIAL ADDRESS"], max_len=150)
    if addr:
        result["Address"] = addr[:200]

    # District & State
    district = re.search(r"(?:DISTRICT)[:\s]*([A-Z\s]{3,30}?)(?:\n|,|$)", t)
    if district:
        result["District"] = district.group(1).strip()
    state = re.search(r"(?:STATE)[:\s]*([A-Z\s]{3,30}?)(?:\n|,|$)", t)
    if state:
        result["State"] = state.group(1).strip()

    # Email & Phone
    email = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", t)
    if email:
        result["Email"] = email.group(0).lower()
    phone = re.search(r"\b([6-9]\d{9})\b", t)
    if phone:
        result["Phone"] = phone.group(1)

    required = ["Udyam Number", "Enterprise Name", "Type of Enterprise"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 8 — DRIVING LICENSE EXTRACTOR
# ─────────────────────────────────────────────

def extract_dl(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # DL Number — state code + digits (various formats across states)
    dl_match = re.search(
        r"\b(?:DL\s*NO|LICENCE\s*NO|LICENSE\s*NO|DL)[:\s.\-]*"
        r"([A-Z]{2}[\s\-]?\d{2}[\s\-]?\d{4}[\s\-]?\d{7}|"
        r"[A-Z]{2}[\s\-]?\d{13}|"
        r"[A-Z]{2}\d{2}\s?\d{11})\b",
        t
    )
    if dl_match:
        result["DL Number"] = re.sub(r"\s+", "", dl_match.group(1))
    else:
        # Broader fallback
        dl_fb = re.search(r"\b([A-Z]{2}[\s\-]?\d{2}[\s\-]?\d{4,11})\b", t)
        if dl_fb:
            result["DL Number"] = re.sub(r"\s+", "", dl_fb.group(1))

    # Name
    name = extract_after_label(t, ["NAME", "HOLDER NAME", "LICENSEE NAME"])
    result["Name"] = clean_name(name) if name else ""

    # Date of Birth
    dob = re.search(
        r"(?:DOB|DATE\s*OF\s*BIRTH|BIRTH\s*DATE)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if dob:
        result["Date of Birth"] = normalize_date(dob.group(1))

    # Valid From / Valid To
    valid_from = re.search(
        r"(?:VALID\s*FROM|ISSUE\s*DATE|DATE\s*OF\s*ISSUE)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if valid_from:
        result["Valid From"] = normalize_date(valid_from.group(1))

    valid_to = re.search(
        r"(?:VALID\s*TO|VALID\s*TILL|EXPIRY|VALID\s*UPTO)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if valid_to:
        result["Valid To"] = normalize_date(valid_to.group(1))

    # Blood Group
    bg = re.search(r"\b(A|B|AB|O)[\s]?[+\-](VE|VE|)\b|BLOOD\s*GRP[:\s]*([A-Z0-9+\-]{2,4})", t)
    if bg:
        result["Blood Group"] = (bg.group(1) or bg.group(3) or "").strip()

    # Address
    addr = extract_after_label(t, ["ADDRESS", "PERMANENT ADDRESS"], max_len=150)
    if addr:
        result["Address"] = addr[:200]

    # Vehicle Classes
    vc = re.search(
        r"(?:CLASS\s*OF\s*VEHICLE|VEHICLE\s*CLASS|COV)[:\s]*([A-Z0-9,\s/]{2,60}?)(?:\n|$)",
        t
    )
    if vc:
        result["Vehicle Class"] = vc.group(1).strip()

    required = ["DL Number", "Name", "Date of Birth", "Valid To"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 9 — RC EXTRACTOR
# ─────────────────────────────────────────────

def extract_rc(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # Registration Number (vehicle plate)
    reg = re.search(
        r"\b(?:REG(?:ISTRATION)?\s*NO|VEHICLE\s*NO|RC\s*NO)[:\s.\-]*"
        r"([A-Z]{2}[\s\-]?\d{2}[\s\-]?[A-Z]{1,3}[\s\-]?\d{4})\b",
        t
    )
    if reg:
        result["Vehicle Number"] = re.sub(r"\s+", "", reg.group(1))
    else:
        # Fallback: standard Indian plate format
        plate = re.search(r"\b([A-Z]{2}\d{2}[A-Z]{1,3}\d{4})\b", t)
        if plate:
            result["Vehicle Number"] = plate.group(1)

    # Owner Name
    owner = extract_after_label(t, ["OWNER", "REGISTERED OWNER", "OWNER NAME", "NAME OF OWNER"])
    result["Owner Name"] = clean_name(owner) if owner else ""

    # Registration Date
    reg_date = re.search(
        r"(?:REG(?:ISTRATION)?\s*DATE|DATE\s*OF\s*REG)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if reg_date:
        result["Registration Date"] = normalize_date(reg_date.group(1))

    # Chassis Number
    chassis = re.search(r"(?:CHASSIS\s*NO|CHASSIS)[:\s.\-]*([A-Z0-9]{10,20})", t)
    if chassis:
        result["Chassis Number"] = chassis.group(1)

    # Engine Number
    engine = re.search(r"(?:ENGINE\s*NO|ENGINE)[:\s.\-]*([A-Z0-9]{6,20})", t)
    if engine:
        result["Engine Number"] = engine.group(1)

    # Make / Model
    make = re.search(r"(?:MAKE|MANUFACTURER|BRAND)[:\s]*([A-Z\s]{2,30}?)(?:\n|,|$)", t)
    if make:
        result["Make"] = make.group(1).strip()
    model = re.search(r"(?:MODEL)[:\s]*([A-Z0-9\s\-]{2,30}?)(?:\n|,|$)", t)
    if model:
        result["Model"] = model.group(1).strip()

    # Fuel Type
    fuel = re.search(r"\b(PETROL|DIESEL|CNG|ELECTRIC|HYBRID|LPG)\b", t)
    if fuel:
        result["Fuel Type"] = fuel.group(1).capitalize()

    # Insurance Validity
    ins = re.search(
        r"(?:INSURANCE|INSURED\s*UPTO|INSURANCE\s*VALID)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if ins:
        result["Insurance Valid Upto"] = normalize_date(ins.group(1))

    # Fitness Validity
    fit = re.search(
        r"(?:FITNESS|FIT\s*UPTO|FITNESS\s*VALID)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4})",
        t
    )
    if fit:
        result["Fitness Valid Upto"] = normalize_date(fit.group(1))

    required = ["Vehicle Number", "Owner Name", "Registration Date"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 10 — RESUME EXTRACTOR
# ─────────────────────────────────────────────

_SKILL_KEYWORDS = {
    "python", "java", "javascript", "js", "typescript", "ts", "c++", "cpp",
    "c#", "csharp", "ruby", "php", "swift", "kotlin", "go", "rust", "scala",
    "react", "angular", "vue", "node", "nodejs", "django", "flask", "spring",
    "html", "css", "sql", "mysql", "postgresql", "mongodb", "redis", "docker",
    "kubernetes", "aws", "azure", "gcp", "git", "linux", "bash", "tensorflow",
    "pytorch", "scikit", "pandas", "numpy", "machine learning", "deep learning",
    "nlp", "data science", "power bi", "tableau", "excel", "r", "matlab",
}

_DEGREE_PATTERNS = [
    r"B\.?\s*TECH", r"M\.?\s*TECH", r"B\.?\s*E\.?", r"M\.?\s*E\.?",
    r"B\.?\s*SC", r"M\.?\s*SC", r"BCA", r"MCA", r"MBA", r"BBA",
    r"B\.?\s*COM", r"M\.?\s*COM", r"B\.?\s*A\.?", r"M\.?\s*A\.?",
    r"PHD", r"PH\.D", r"DIPLOMA", r"B\.?\s*PHARM", r"M\.?\s*PHARM",
    r"MBBS", r"B\.?\s*ARCH",
]


def extract_resume(text: str) -> tuple:
    t = preprocess_text(text)
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    result = {}

    # Candidate Name — first non-header line that looks like a name
    for line in lines[:8]:
        if (re.match(r"^[A-Z][A-Z\s.]{3,40}$", line)
                and not any(kw in line for kw in [
                    "RESUME", "CV", "CURRICULUM", "VITAE", "OBJECTIVE",
                    "PROFILE", "SUMMARY", "CONTACT"
                ])):
            result["Candidate Name"] = line.title()
            break

    # Email
    email = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", t)
    if email:
        result["Email"] = email.group(0).lower()

    # Phone — Indian + international formats
    phone = re.search(
        r"(?:\+91[\s\-]?)?(?:\(?0?\d{2,4}\)?[\s\-]?)?\b([6-9]\d{9})\b"
        r"|(?:\+\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}",
        t
    )
    if phone:
        result["Phone"] = (phone.group(1) or phone.group(0)).strip()

    # LinkedIn / GitHub
    linkedin = re.search(r"LINKEDIN\.COM/IN/([A-Z0-9\-]+)", t)
    if linkedin:
        result["LinkedIn"] = "linkedin.com/in/" + linkedin.group(1).lower()
    github = re.search(r"GITHUB\.COM/([A-Z0-9\-]+)", t)
    if github:
        result["GitHub"] = "github.com/" + github.group(1).lower()

    # Skills — extract section then tokenize
    skills_section = re.search(
        r"SKILLS?[:\-\s]+([\s\S]{10,400}?)(?=\n[A-Z]{4,}|\Z)",
        t
    )
    if skills_section:
        raw_skills = skills_section.group(1)
        tokens = re.split(r"[,|•\n/]+", raw_skills)
        found_skills = []
        for tok in tokens:
            tok = tok.strip().lower()
            if tok in _SKILL_KEYWORDS or any(kw in tok for kw in _SKILL_KEYWORDS):
                found_skills.append(tok.title())
            elif 2 <= len(tok) <= 25 and re.match(r"^[a-z0-9\s.#+\-]+$", tok):
                found_skills.append(tok.title())
        result["Skills"] = list(dict.fromkeys(found_skills))[:20]

    # Education — find degrees with institutions and years
    edu_items = []
    for deg_pat in _DEGREE_PATTERNS:
        for m in re.finditer(deg_pat, t):
            start = max(0, m.start() - 5)
            end = min(len(t), m.end() + 120)
            snippet = t[start:end]
            year_match = re.search(r"(20\d{2}|19\d{2})", snippet)
            year = year_match.group(1) if year_match else ""
            edu_items.append({
                "degree": m.group(0).replace(".", "").strip(),
                "year": year
            })
    if edu_items:
        result["Education Items"] = edu_items
        result["Education"] = ", ".join(
            e["degree"] + (f" ({e['year']})" if e["year"] else "")
            for e in edu_items
        )

    # Experience — total years
    exp_years = re.search(r"(\d+\.?\d*)\+?\s*YEARS?\s*(?:OF\s*)?(?:EXPERIENCE|EXP)", t)
    if exp_years:
        result["Experience Years"] = exp_years.group(1) + "+ years"

    # Experience section — job titles and companies
    exp_section = re.search(
        r"(?:WORK\s*EXPERIENCE|EXPERIENCE|EMPLOYMENT)[:\-\s]+([\s\S]{10,600}?)"
        r"(?=\n(?:EDUCATION|SKILLS?|PROJECTS?|CERTIF|\Z))",
        t
    )
    if exp_section:
        result["Experience"] = re.sub(r"\s+", " ", exp_section.group(1)).strip()[:300]

    # Summary / Objective
    summary = re.search(
        r"(?:SUMMARY|OBJECTIVE|PROFILE|ABOUT\s*ME)[:\-\s]+([\s\S]{10,300}?)"
        r"(?=\n[A-Z]{4,}|\Z)",
        t
    )
    if summary:
        result["Summary"] = re.sub(r"\s+", " ", summary.group(1)).strip()[:250]

    required = ["Candidate Name", "Email", "Phone", "Skills"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 11 — AGREEMENT & AFFIDAVIT
# ─────────────────────────────────────────────

def extract_agreement(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # Parties
    p1 = extract_after_label(t, ["FIRST PARTY", "PARTY A", "PARTY OF THE FIRST PART"])
    if p1:
        result["Party 1"] = clean_name(p1)
    p2 = extract_after_label(t, ["SECOND PARTY", "PARTY B", "PARTY OF THE SECOND PART"])
    if p2:
        result["Party 2"] = clean_name(p2)

    # Date
    dated = re.search(
        r"(?:AGREEMENT\s*DATE|DATED|THIS\s*AGREEMENT\s*IS\s*MADE\s*ON)[:\s.\-]*"
        r"(\d{2}[/.\-]\d{2}[/.\-]\d{4}|\d{1,2}\s+[A-Z]+\s+\d{4})",
        t
    )
    if dated:
        result["Agreement Date"] = normalize_date(dated.group(1))

    # Subject
    subj = extract_after_label(t, ["SUBJECT", "RE:", "REGARDING"])
    if subj:
        result["Subject"] = subj[:100]

    # Clause count
    clauses = re.findall(r"\bCLAUSE\s*\d+|\b\d+\.\s+[A-Z]", t)
    if clauses:
        result["Clause Count"] = len(set(clauses))

    # Jurisdiction
    juris = re.search(r"(?:JURISDICTION|GOVERNED\s*BY)[:\s]*([A-Z\s,]{3,40}?)(?:\n|$)", t)
    if juris:
        result["Jurisdiction"] = juris.group(1).strip()

    required = ["Party 1", "Party 2", "Agreement Date"]
    return result, score_extraction(result, required)


def extract_affidavit(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    # Deponent Name
    dep = re.search(
        r"(?:I|DEPONENT|DEPONENT\s*NAME)[,:\s]+([A-Z][A-Z\s.]{3,40}?)"
        r"(?:\s*(?:DO\s*HEREBY|SOLEMNLY|S/O|D/O|AGE|AGED))",
        t
    )
    if dep:
        result["Deponent Name"] = clean_name(dep.group(1))

    # Age
    age = re.search(r"(?:AGED|AGE)[:\s]*(\d{2})\s*(?:YEARS?)?", t)
    if age:
        result["Age"] = age.group(1)

    # Address of deponent
    addr = extract_after_label(t, ["RESIDING AT", "R/O", "ADDRESS"], max_len=120)
    if addr:
        result["Address"] = addr[:150]

    # Date
    dated = re.search(
        r"(?:DATED|DATE)[:\s.\-]*(\d{2}[/.\-]\d{2}[/.\-]\d{4}|\d{1,2}\s+[A-Z]+\s+\d{4})",
        t
    )
    if dated:
        result["Date"] = normalize_date(dated.group(1))

    # Subject / Purpose
    subj = extract_after_label(t, ["SUBJECT", "REGARDING", "PURPOSE"])
    if subj:
        result["Subject"] = subj[:100]

    # Notary
    notary = extract_after_label(t, ["NOTARY", "NOTARY PUBLIC", "NOTARY NAME"])
    if notary:
        result["Notary"] = clean_name(notary)

    required = ["Deponent Name", "Date"]
    return result, score_extraction(result, required)


# ─────────────────────────────────────────────
# SECTION 12 — GENERIC FALLBACK
# ─────────────────────────────────────────────

def extract_generic(text: str) -> tuple:
    t = preprocess_text(text)
    result = {}

    email = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", t)
    if email:
        result["Email"] = email.group(0).lower()

    phone = re.search(r"\b([6-9]\d{9})\b", t)
    if phone:
        result["Phone"] = phone.group(1)

    dates = re.findall(r"\b\d{2}[/.\-]\d{2}[/.\-]\d{4}\b", t)
    if dates:
        result["Dates Found"] = [normalize_date(d) for d in dates[:3]]

    # Any 10-char alphanumeric that looks like an ID
    ids = re.findall(r"\b[A-Z]{2,5}\d{4,10}[A-Z0-9]{0,4}\b", t)
    if ids:
        result["Possible IDs"] = list(dict.fromkeys(ids))[:3]

    return result, score_extraction(result, ["Email", "Phone"])


# ─────────────────────────────────────────────
# SECTION 13 — MAIN ENTRY POINT
# ─────────────────────────────────────────────

_EXTRACTORS = {
    "PAN":      extract_pan,
    "AADHAAR":  extract_aadhaar,
    "GST":      extract_gst,
    "FSSAI":    extract_fssai,
    "UDYAM":    extract_udyam,
    "DL":       extract_dl,
    "RC":       extract_rc,
    "RESUME":   extract_resume,
    "AGREEMENT":extract_agreement,
    "AFFIDAVIT":extract_affidavit,
}


def extract_document(text: str, multi: bool = False) -> dict:
    """
    Main extraction entry point.
    1. Detect document type(s) using score-based rules
    2. Run matching extractor(s)
    3. Pick best result by extraction score
    4. Attach confidence score
    5. Fall back to generic if nothing detected
    """
    if not text or not text.strip():
        return {"Error": "Empty document — no text could be extracted.", "Confidence": 0}

    doc_types = detect_doc_types(text)
    logger.debug(f"Detected doc types: {doc_types}")

    results = []
    for doc_type in doc_types:
        extractor = _EXTRACTORS.get(doc_type)
        if not extractor:
            continue
        try:
            extracted, score = extractor(text)
        except Exception as e:
            logger.warning(f"Extractor {doc_type} failed: {e}")
            continue
        if extracted:
            results.append({
                "Document Type": doc_type,
                "_score": score,
                **extracted
            })

    if results:
        best = max(results, key=lambda r: r.get("_score", 0))
        confidence = best.pop("_score", 0)
        best["Confidence"] = confidence
        return best

    # Generic fallback
    extracted, score = extract_generic(text)
    if extracted:
        extracted["Document Type"] = "OTHER"
        extracted["Confidence"] = score
        return extracted

    return {"Error": "No data could be extracted from this document.", "Confidence": 0}


# ─────────────────────────────────────────────
# SECTION 14 — AI INSIGHTS
# ─────────────────────────────────────────────

# Expected fields per document type for missing-field analysis
_EXPECTED_FIELDS = {
    "PAN":      ["PAN Number", "Name", "Father's Name", "Date of Birth"],
    "AADHAAR":  ["Aadhaar Number", "Name", "Date of Birth", "Gender", "Address"],
    "GST":      ["GST Number", "Legal Name", "Date of Registration", "Address"],
    "FSSAI":    ["FSSAI Number", "Business Name", "Valid Upto", "Address"],
    "UDYAM":    ["Udyam Number", "Enterprise Name", "Owner Name", "Type of Enterprise"],
    "DL":       ["DL Number", "Name", "Date of Birth", "Valid To", "Blood Group"],
    "RC":       ["Vehicle Number", "Owner Name", "Registration Date", "Chassis Number"],
    "RESUME":   ["Candidate Name", "Email", "Phone", "Skills", "Education"],
    "AGREEMENT":["Party 1", "Party 2", "Agreement Date"],
    "AFFIDAVIT":["Deponent Name", "Date", "Subject"],
}


def generate_ai_insights(result: dict) -> dict:
    """
    Generate structured insights from extracted data:
    - Summary sentence
    - Confidence level label
    - Keywords from values
    - Missing fields vs expected
    - Validation flags (e.g. expired document)
    """
    if not isinstance(result, dict):
        return {"summary": "No insights available.", "keywords": [], "missing_fields": []}

    doc_type = result.get("Document Type", "Unknown")
    confidence = result.get("Confidence", 0)
    expected = _EXPECTED_FIELDS.get(doc_type, [])

    # Determine present vs missing
    present = [f for f in expected if result.get(f)]
    missing = [f for f in expected if not result.get(f)]

    # Confidence label
    if confidence >= 80:
        conf_label = "High"
    elif confidence >= 50:
        conf_label = "Medium"
    else:
        conf_label = "Low"

    # Summary
    summary = (
        f"{doc_type} document detected with {conf_label} confidence ({confidence}%). "
        f"{len(present)} of {len(expected)} expected fields extracted."
    )
    if missing:
        summary += f" Missing: {', '.join(missing[:3])}{'…' if len(missing) > 3 else ''}."

    # Expiry check
    flags = []
    from datetime import date
    today = date.today()
    for key in ["Valid To", "Valid Upto", "Validity", "Subscription Expiry", "Insurance Valid Upto"]:
        val = result.get(key)
        if val:
            try:
                exp = datetime.strptime(val, "%Y-%m-%d").date()
                if exp < today:
                    flags.append(f"⚠️ {key} has expired ({val})")
                elif (exp - today).days <= 30:
                    flags.append(f"⏳ {key} expiring soon ({val})")
            except Exception:
                pass

    # Keywords from values
    all_values = " ".join(
        str(v) for k, v in result.items()
        if k not in ("Document Type", "Confidence", "Error") and v
    ).upper()
    tokens = re.findall(r"[A-Z0-9]{3,}", all_values)
    seen = set()
    keywords = []
    for t in tokens:
        if t not in seen and not t.isdigit() and len(t) >= 3:
            seen.add(t)
            keywords.append(t)
        if len(keywords) >= 12:
            break

    return {
        "summary": summary,
        "confidence_label": conf_label,
        "keywords": keywords,
        "missing_fields": missing,
        "flags": flags,
    }
