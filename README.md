# SmartDocX 📄

> AI-powered document data extractor for Indian documents — built with Django, Tesseract OCR, and TailwindCSS.

---

## What it does

SmartDocX lets you upload scanned PDFs or images of Indian identity and business documents and instantly extracts structured data from them using OCR + smart regex parsing.

**Supported document types:**
`PAN` · `Aadhaar` · `GST` · `FSSAI` · `Udyam` · `Driving License` · `RC Book` · `Resume/CV` · `Agreement` · `Affidavit`

---

## Features

- 🔍 **Auto-detect** document type or manually select
- 📦 **Batch upload** — process multiple files at once
- 🔁 **Duplicate detection** via SHA-256 file hashing
- 📊 **Dashboard** with KPI cards, charts, and activity feed
- 🧾 **Document history** with filters (type, date, confidence)
- 🔀 **Side-by-side comparison** of any two documents
- 🤖 **AI Insights** — summary, keywords, missing fields
- ⬇️ **Export** per-document as JSON or CSV, bulk as Excel
- 💎 **Subscription plans** with token-based usage
- 🌙 **Dark mode** support
- 🔒 File validation, rate limiting, path traversal protection

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Django 5.x, Python 3.13 |
| OCR | Tesseract via `pytesseract`, PyMuPDF (`fitz`) |
| Frontend | TailwindCSS (CDN), Chart.js, SweetAlert2, AOS |
| Database | SQLite (dev) |
| Auth | Django built-in auth |

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/Samzz2500/SmartDocX.git
cd SmartDocX
```

### 2. Create virtual environment
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac
```

### 3. Install dependencies
```bash
pip install django pillow pytesseract pymupdf openpyxl
```

### 4. Install Tesseract OCR
Download and install from: https://github.com/UB-Mannheim/tesseract/wiki

Then update the path in `extractor/views.py`:
```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

### 5. Run migrations
```bash
python manage.py migrate
```

### 6. Seed subscription plans
```bash
python manage.py seedplans
```

### 7. Create superuser (optional)
```bash
python manage.py createsuperuser
```

### 8. Start the server
```bash
python manage.py runserver
```

Visit: http://127.0.0.1:8000

---

## Project Structure

```
SmartDocX/
├── docextractor/        # Django project settings & URLs
├── extractor/           # Core app — models, views, OCR utils, extraction engine
│   ├── templates/
│   ├── management/commands/   # seedplans, seed_demo
│   └── migrations/
├── users/               # Auth app — dashboard, profile, settings, feedback
│   └── templates/
├── templates/           # Global base.html, landing.html
├── media/               # Uploaded files (gitignored)
└── manage.py
```

---

## Pages

| URL | Description |
|---|---|
| `/` | Landing page |
| `/login/` | Login |
| `/register/` | Register |
| `/dashboard/` | User dashboard with stats & upload |
| `/extractor/` | Batch upload page |
| `/extractor/history/` | Document history with filters |
| `/extractor/document/<id>/` | Extracted data detail view |
| `/extractor/compare/` | Side-by-side document comparison |
| `/extractor/subscriptions/` | Subscription plans |
| `/profile/` | User profile |
| `/settings/` | Account settings |
| `/contact/` | Feedback form |
| `/admin/` | Django admin |

---

## Demo seed data

```bash
python manage.py seed_demo
```

Creates 6 sample documents per user for testing the dashboard and history.

---

## Environment Notes

- `DEBUG = True` and `ALLOWED_HOSTS` includes `localhost` — change before deploying
- `SECRET_KEY` in `settings.py` must be rotated for production
- SQLite is used by default — swap for PostgreSQL in production

---

## Developed by

**Team Evolve Infotech**  
GitHub: [@Samzz2500](https://github.com/Samzz2500)
