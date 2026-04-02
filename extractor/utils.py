import re
from datetime import datetime

# ---------------- CLEANING + HELPERS ----------------
def clean_value(value):
    """Normalize and clean extracted text values."""
    if isinstance(value, list):
        cleaned = [v.strip().replace("\n", " ").replace("  ", " ") for v in value if v and v.strip()]
        return list(dict.fromkeys(cleaned))
    return value.strip().replace("\n", " ").replace("  ", " ") if isinstance(value, str) else value


def preprocess_text(raw: str) -> str:
    """Light OCR cleanup to improve regex hit-rate.
    - Normalize whitespace
    - Fix common OCR confusions: O→0, I/l→1 in numeric contexts, S→5 in numeric groups, Z↔2 in tails
    - Uppercase for consistent matching
    """
    if not raw:
        return ""
    text = raw
    # Normalize newlines and spaces
    text = re.sub(r"[\r\t\f]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    # Upper for id patterns
    text = text.upper()

    # Heuristic replacements inside alnum sequences typically used in IDs
    def fix_ocr_token(token: str) -> str:
        t = token
        # Replace letter O with zero when surrounded by digits or in long digit groups
        t = re.sub(r"(?<=\d)O(?=\d)", "0", t)
        # Replace I or L with 1 in numeric groups
        t = re.sub(r"(?<=\d)[IL](?=\d)", "1", t)
        # Replace S with 5 in numeric groups
        t = re.sub(r"(?<=\d)S(?=\d)", "5", t)
        # Replace Z with 2 at the end of GST-like tokens if flanked by digits
        t = re.sub(r"(?<=\d)Z(?=\d$)", "2", t)
        return t

    text = " ".join(fix_ocr_token(tok) for tok in text.split(" "))
    return text


def normalize_date(date_str):
    """Convert detected dates to ISO YYYY-MM-DD format if possible."""
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y",
        "%d %B %Y", "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return date_str


def extract_with_patterns(text, patterns):
    """Generic regex extractor with auto-cleaning. Returns plain values only."""
    extracted = {}
    text = preprocess_text(text)

    for key, pattern in patterns.items():
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if matches:
            value = matches if len(matches) > 1 else matches[0]
            value = clean_value(value)

            # Normalize field-specific data
            if "date" in key.lower():
                if isinstance(value, list):
                    value = [normalize_date(v) for v in value]
                else:
                    value = normalize_date(value)

            if "number" in key.lower() or "id" in key.lower():
                if isinstance(value, list):
                    value = [v.upper().replace(" ", "") for v in value]
                else:
                    value = value.upper().replace(" ", "")

            if "address" in key.lower():
                if isinstance(value, list):
                    value = [v.replace(",", ", ").strip() for v in value]
                else:
                    value = value.replace(",", ", ").strip()

            extracted[key] = value

    # Score number of fields matched for tie-breaking (not returned)
    score = len(extracted)
    return extracted, score


# ---------------- INDIVIDUAL DOC EXTRACTORS ----------------
def extract_gst(text):
    patterns = {
        # Allow optional spaces and common OCR substitutions fixed upstream
        "GST Number": r"\b\d{2}\s*[A-Z]{5}\s*\d{4}\s*[A-Z]\s*\d\s*[A-Z0-9]\s*Z\s*[A-Z0-9]\b",
        "Legal Name": r"LEGAL\s*NAME[:\-]?\s*([A-Z\s&,.]+)",
        "Trade Name": r"TRADE\s*NAME[:\-]?\s*([A-Z\s&,.]+)",
        "Address": r"(?:PRINCIPAL\s*)?ADDRESS[:\-]?\s*([A-Z0-9\s,./-]+)",
        "Date of Registration": r"(?:DATE\s*OF\s*REGISTRATION|REGISTRATION\s*DATE)[:\-]?\s*([\d./-]+)",
        "Email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "Phone": r"\b\d{10}\b",
    }
    return extract_with_patterns(text, patterns)


def extract_pan(text):
    patterns = {
        "PAN Number": r"\b[A-Z]{5}\s*\d{4}\s*[A-Z]\b",
        "Name": r"(?:NAME|HOLDER\s*NAME)[:\-]?\s*([A-Z\s.]+)",
        "Father's Name": r"FATHER'?S\s*NAME[:\-]?\s*([A-Z\s.]+)",
        "Date of Birth": r"(?:DOB|DATE\s*OF\s*BIRTH)[:\-]?\s*([\d./-]+)",
    }
    return extract_with_patterns(text, patterns)


def extract_fssai(text):
    patterns = {
        "FSSAI Number": r"\b\d{14}\b",
        "Business Name": r"(?:BUSINESS|COMPANY|RESTAURANT)\s*NAME[:\-]?\s*([A-Z\s&,.]+)",
        "Address": r"ADDRESS[:\-]?\s*([A-Z0-9\s,./-]+)",
        "Validity": r"(?:VALID\s*UPTO|VALIDITY\s*DATE)[:\-]?\s*([\d./-]+)",
        "Email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "Phone": r"\b\d{10}\b",
    }
    return extract_with_patterns(text, patterns)


def extract_aadhaar(text):
    patterns = {
        "Aadhaar Number": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
        "Name": r"(?:NAME|HOLDER\s*NAME)[:\-]?\s*([A-Z\s.]+)",
        "Date of Birth": r"(?:DOB|DATE\s*OF\s*BIRTH)[:\-]?\s*([\d./-]+)",
        "Gender": r"\b(MALE|FEMALE|TRANSGENDER|M|F)\b",
        "Address": r"ADDRESS[:\-]?\s*([A-Z0-9\s,./-]+)",
    }
    return extract_with_patterns(text, patterns)


def extract_udyam(text):
    patterns = {
        "Udyam Number": r"\bUDYAM-[A-Z]{2}-\d{2}-\d{7}\b",
        "Enterprise Name": r"(?:ENTERPRISE|BUSINESS)\s*NAME[:\-]?\s*([A-Z\s&,.]+)",
        "Type of Enterprise": r"TYPE\s*OF\s*ENTERPRISE[:\-]?\s*([A-Z\s]+)",
        "Address": r"ADDRESS[:\-]?\s*([A-Z0-9\s,./-]+)",
        "Date of Incorporation": r"(?:DATE\s*OF\s*INCORPORATION|INCORPORATION\s*DATE)[:\-]?\s*([\d./-]+)",
    }
    return extract_with_patterns(text, patterns)


# ---------------- DOC TYPE DETECTION ----------------
def detect_doc_types(text):
    """Detect possible document types based on patterns and keywords."""
    text_upper = preprocess_text(text)
    doc_types = []

    if re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d]Z[A-Z\d]\b", text_upper) or "GSTIN" in text_upper:
        doc_types.append("GST")
    if re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text_upper) or "INCOME TAX DEPARTMENT" in text_upper:
        doc_types.append("PAN")
    if re.search(r"\b\d{14}\b", text_upper) or "FSSAI" in text_upper:
        doc_types.append("FSSAI")
    if re.search(r"\b\d{4}\s\d{4}\s\d{4}\b", text_upper) or "UNIQUE IDENTIFICATION AUTHORITY" in text_upper or "AADHAAR" in text_upper:
        doc_types.append("AADHAAR")
    if re.search(r"\bUDYAM-[A-Z]{2}-\d{2}-\d{7}\b", text_upper) or "UDYAM REGISTRATION" in text_upper:
        doc_types.append("UDYAM")
    # Resume/CV detection
    if "RESUME" in text_upper or "CURRICULUM VITAE" in text_upper or re.search(r"\bCV\b", text_upper):
        doc_types.append("RESUME")
    # DL detection
    if re.search(r"\bDL\s*NO[:\-]?\s*[A-Z]{2}\d{2}\d{4}\d{7}\b", text_upper) or "DRIVING LICENCE" in text_upper or "DRIVING LICENSE" in text_upper:
        doc_types.append("DL")
    # RC detection
    if re.search(r"\bRC\s*NO[:\-]?\s*[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}\b", text_upper) or "REGISTRATION CERTIFICATE" in text_upper:
        doc_types.append("RC")
    # Agreement detection
    if "AGREEMENT" in text_upper and ("BETWEEN" in text_upper or "PARTIES" in text_upper):
        doc_types.append("AGREEMENT")
    # Affidavit detection
    if "AFFIDAVIT" in text_upper or "I DO SOLEMNLY AFFIRM" in text_upper:
        doc_types.append("AFFIDAVIT")

    return doc_types


# ---------------- GENERIC FALLBACK ----------------
def extract_generic(text):
    patterns = {
        "Email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "Phone": r"\b\d{10}\b",
        "Dates": r"\b\d{2}[./-]\d{2}[./-]\d{4}\b",
    }
    extracted, score = extract_with_patterns(text, patterns)
    return extracted, score


# ---------------- MAIN ENTRY ----------------
def extract_document(text, multi=False):
    """Main extractor for SmartDocX (viva-ready version)."""
    extractors = {
        "GST": extract_gst,
        "PAN": extract_pan,
        "FSSAI": extract_fssai,
        "AADHAAR": extract_aadhaar,
        "UDYAM": extract_udyam,
        "RESUME": extract_resume,
        "DL": extract_dl,
        "RC": extract_rc,
        "AGREEMENT": extract_agreement,
        "AFFIDAVIT": extract_affidavit,
    }

    doc_types = detect_doc_types(text)
    results = []

    if doc_types:
        for doc_type in doc_types:
            extractor_func = extractors.get(doc_type)
            if extractor_func:
                extracted, score = extractor_func(text)
                if extracted:
                    results.append({
                        "Document Type": doc_type,
                        "_score": score,
                        **extracted
                    })
        # Pick document type with highest score
        if results:
            best = max(results, key=lambda r: r.get("_score", 0))
            best.pop("_score", None)
            return best
    else:
        extracted, score = extract_generic(text)
        if extracted:
            return {"Document Type": "UNKNOWN", **extracted}

    return {"Error": "No data extracted", "Confidence": 0}


# ---------------- RESUME PARSER ----------------
def extract_resume(text):
    """Extract common resume fields.
    Fields: Candidate Name, Email, Phone, Skills, Education, Experience Years/Items.
    """
    patterns = {
        "Candidate Name": r"^(?:RESUME\s*)?([A-Z][A-Z\s'.-]{2,})\b",
        "Email": r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        "Phone": r"(?:\+?\d{1,3}[\s-]?)?(?:\d{10}|\d{3}[\s-]?\d{3}[\s-]?\d{4})",
        # Skills: comma/pipe separated line containing keywords
        "Skills": r"SKILLS?[:\-]?\s*([A-Z0-9 ,/|+.#()-]{5,})",
        # Education: Degree + Year/Institution lines
        "Education": r"(B\.?(TECH|E)|M\.?(TECH|E)|BSC|MSC|BCA|MCA|MBA|B\.?COM|M\.?COM)[A-Z0-9\s,().-]*",
        # Experience: years or bullet section
        "Experience": r"(\d+\+?\s*YEARS?|EXPERIENCE[:\-]?[A-Z0-9\s,().-]+)",
    }
    extracted, score = extract_with_patterns(text, patterns)
    # Split skills by separators if present
    skills = extracted.get("Skills")
    if isinstance(skills, str):
        parts = re.split(r"[,|/]+", skills)
        parts = [p.strip() for p in parts if p.strip()]
        if parts:
            # Normalize common abbreviations
            map_norm = {
                "js": "JavaScript", "node": "Node.js", "react": "React",
                "py": "Python", "cpp": "C++", "c#": "C#", "ts": "TypeScript",
                "ml": "Machine Learning", "dl": "Deep Learning"
            }
            norm = []
            for p in parts:
                key = p.lower()
                norm.append(map_norm.get(key, p))
            extracted["Skills"] = sorted(set(norm), key=lambda x: norm.index(x))

    # Parse education entries with years (e.g., 2018-2022)
    edu = extracted.get("Education")
    if edu:
        lines = re.findall(r"(B\.?TECH|M\.?TECH|B\.?E|M\.?E|BSC|MSC|BCA|MCA|MBA|B\.?COM|M\.?COM)[A-Z0-9\s,().-]*", preprocess_text(edu))
        year_ranges = re.findall(r"(20\d{2})\s*[-–]\s*(20\d{2})", preprocess_text(text))
        if lines or year_ranges:
            extracted["Education Items"] = []
            for deg in set([l[0] if isinstance(l, tuple) else l for l in lines] or []):
                extracted["Education Items"].append({"degree": deg})
            for yr in year_ranges:
                extracted["Education Items"].append({"years": f"{yr[0]}-{yr[1]}"})

    # Parse experience years like "3 years", "2+ years"
    exp = extracted.get("Experience")
    if exp:
        yrs = re.findall(r"(\d+\+?)\s*YEARS?", preprocess_text(exp))
        if yrs:
            extracted["Experience Years"] = yrs[0]
    return extracted, score


# ---------------- DL (Driving License) ----------------
def extract_dl(text):
    """Extract DL fields: DL Number, Name, DOB, Validity, Address."""
    patterns = {
        "DL Number": r"DL\s*NO[:\-]?\s*([A-Z]{2}\d{2}\d{4}\d{7})",
        "Name": r"(?:NAME|HOLDER\s*NAME)[:\-]?\s*([A-Z\s.]+)",
        "Date of Birth": r"(?:DOB|DATE\s*OF\s*BIRTH)[:\-]?\s*([\d./-]+)",
        "Validity": r"(?:VALID\s*FROM|VALID\s*TO)[:\-]?\s*([\d./-]+)",
        "Address": r"ADDRESS[:\-]?\s*([A-Z0-9\s,./-]+)",
        "Blood Group": r"BLOOD\s*GROUP[:\-]?\s*([A-Z]{1,2}\+?\-?)",
    }
    return extract_with_patterns(text, patterns)


# ---------------- RC (Registration Certificate) ----------------
def extract_rc(text):
    """Extract RC fields: RC Number, Vehicle Number, Owner Name, Registration Date."""
    patterns = {
        "RC Number": r"RC\s*NO[:\-]?\s*([A-Z]{2}\d{2}[A-Z]{1,2}\d{4})",
        "Vehicle Number": r"(?:VEHICLE\s*NO|REG\s*NO)[:\-]?\s*([A-Z]{2}\d{2}[A-Z]{1,2}\d{4})",
        "Owner Name": r"(?:OWNER|REGISTERED\s*OWNER)[:\-]?\s*([A-Z\s.]+)",
        "Registration Date": r"(?:REG\s*DATE|REGISTRATION\s*DATE)[:\-]?\s*([\d./-]+)",
        "Chassis Number": r"CHASSIS[:\-]?\s*([A-Z0-9]+)",
        "Engine Number": r"ENGINE[:\-]?\s*([A-Z0-9]+)",
    }
    return extract_with_patterns(text, patterns)


# ---------------- AGREEMENT ----------------
def extract_agreement(text):
    """Extract agreement fields: Parties, Date, Subject, Clauses."""
    patterns = {
        "Party 1": r"(?:FIRST\s*PARTY|PARTY\s*A)[:\-]?\s*([A-Z\s&,.]+)",
        "Party 2": r"(?:SECOND\s*PARTY|PARTY\s*B)[:\-]?\s*([A-Z\s&,.]+)",
        "Agreement Date": r"(?:AGREEMENT\s*DATE|DATED)[:\-]?\s*([\d./-]+)",
        "Subject": r"(?:SUBJECT|THIS\s*AGREEMENT)[:\-]?\s*([A-Z0-9\s,.-]+)",
    }
    extracted, score = extract_with_patterns(text, patterns)
    # Count clauses
    clauses = re.findall(r"CLAUSE\s*\d+", preprocess_text(text))
    if clauses:
        extracted["Clause Count"] = len(set(clauses))
    return extracted, score


# ---------------- AFFIDAVIT ----------------
def extract_affidavit(text):
    """Extract affidavit fields: Deponent Name, Date, Subject, Notary."""
    patterns = {
        "Deponent Name": r"(?:I|DEPONENT)[:\-]?\s*([A-Z\s.]+)\s*(?:DO\s*SOLEMNLY|AFFIRM)",
        "Affidavit Date": r"(?:AFFIDAVIT\s*DATE|DATED)[:\-]?\s*([\d./-]+)",
        "Subject": r"(?:REGARDING|SUBJECT)[:\-]?\s*([A-Z0-9\s,.-]+)",
        "Notary Name": r"NOTARY[:\-]?\s*([A-Z\s.]+)",
        "Notary Seal": r"SEAL[:\-]?\s*([A-Z0-9\s]+)",
    }
    return extract_with_patterns(text, patterns)


# ---------------- AI INSIGHTS (lightweight) ----------------
def generate_ai_insights(result: dict):
    """Generate a simple insights summary from an extracted result dict.
    Expects keys like 'Document Type', other fields possibly as dicts {value, confidence}.
    """
    if not isinstance(result, dict):
        return {"summary": "No insights available", "keywords": [], "missing_fields": []}

    doc_type = result.get("Document Type", "Unknown")
    # Gather fields (ignore meta keys)
    field_items = [(k, v) for k, v in result.items() if k not in ("Document Type", "Confidence")]

    values = []
    missing = []
    for k, v in field_items:
        if isinstance(v, dict):
            val = v.get("value")
        else:
            val = v
        if val:
            values.append(str(val))
        else:
            missing.append(k)

    # Naive keyword extraction: split on non-word, filter short tokens
    text_blob = " ".join(values).upper()
    tokens = re.findall(r"[A-Z0-9]{3,}", text_blob)
    # Deduplicate while preserving order
    seen = set(); keywords = []
    for t in tokens:
        if t not in seen and not t.isdigit():
            seen.add(t); keywords.append(t)
        if len(keywords) >= 10:
            break

    # Build summary line
    summary = f"Likely {doc_type} with {len(field_items) - len(missing)} fields detected."
    if missing:
        summary += f" Missing: {', '.join(missing[:3])}{'…' if len(missing)>3 else ''}."

    return {"summary": summary, "keywords": keywords, "missing_fields": missing}
