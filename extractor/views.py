import csv
import openpyxl
import datetime
import os
import hashlib
import fitz
from PIL import Image
import pytesseract
import logging
from django.http import HttpResponse
from django.utils.dateparse import parse_date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q
from django.utils.timezone import now
from django.views.decorators.http import require_http_methods

from .models import UploadedDocument, UsageLog, SubscriptionPlan, Profile
from .utils import extract_document, generate_ai_insights
from .validators import validate_file_size, validate_file_type, sanitize_filename
from .decorators import rate_limit

logger = logging.getLogger(__name__)

# ✅ Path for Tesseract (adjust if needed)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ------------------ SUBSCRIPTIONS ------------------
@login_required
def subscription_plans(request):
    plans = SubscriptionPlan.objects.all()
    return render(request, "extractor/subscriptions.html", {"plans": plans})


@login_required
def dummy_payment(request, plan_id):
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    return render(request, "extractor/dummy_payment.html", {"plan": plan})


@login_required
def payment_success(request, plan_id):
    if request.method != "POST":
        return redirect("subscription_plans")
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    profile, _ = Profile.objects.get_or_create(user=request.user)

    # Only add tokens if not already on unlimited
    if profile.tokens <= 1000000:
        profile.tokens += plan.tokens
    profile.subscription_plan = plan
    profile.subscription_expiry = datetime.date.today() + datetime.timedelta(days=plan.duration_days)
    profile.save()

    messages.success(request, f"🎉 {plan.name} activated! {plan.tokens} tokens added.")
    return render(request, "extractor/payment_success.html", {"plan": plan})


@login_required
def subscribe_plan(request, plan_id):
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if profile.tokens <= 1000000:
        profile.tokens += plan.tokens
    profile.subscription_plan = plan
    profile.subscription_expiry = datetime.date.today() + datetime.timedelta(days=plan.duration_days)
    profile.save()

    messages.success(request, f"✅ Subscribed to {plan.name}. Tokens added.")
    return redirect("dashboard")


# ------------------ DOCUMENT HANDLING ------------------
@login_required
@rate_limit(max_requests=20, window=60)
def home(request):
    """Main dashboard: upload docs, view history, stats."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    # Graceful subscription expiry handling
    if profile.subscription_expiry and profile.subscription_expiry < datetime.date.today():
        profile.subscription_plan = None
        profile.subscription_expiry = None
        profile.save()
    context = {}

    # ---------------- Upload Handling ----------------
    if request.method == "POST":
        documents = request.FILES.getlist("documents")
        if not documents:
            messages.error(request, "⚠️ Please select at least one file.")
        else:
            processed = 0
            last_uploaded = None
            duplicates = []
            temp_dir = os.path.join(settings.MEDIA_ROOT, "temp")
            os.makedirs(temp_dir, exist_ok=True)
            unlimited = profile.tokens and profile.tokens > 1000000
            for document in documents:
                # Security: validate and sanitize
                try:
                    validate_file_size(document)
                    validate_file_type(document)
                    safe_name = sanitize_filename(document.name)
                except Exception as e:
                    messages.error(request, f"⚠️ {str(e)}")
                    logger.warning(f"File validation failed: {e}")
                    continue
                
                temp_path = os.path.join(temp_dir, safe_name)
                with open(temp_path, "wb+") as f:
                    for chunk in document.chunks():
                        f.write(chunk)

                file_hash = hashlib.sha256(open(temp_path, "rb").read()).hexdigest()
                existing = UploadedDocument.objects.filter(file_hash=file_hash, user=request.user).first()
                if existing:
                    last_uploaded = existing
                    duplicates.append(existing)
                    continue

                if not unlimited and profile.tokens <= 0:
                    messages.error(request, "❌ No tokens left. Please upgrade your plan.")
                    break

                text = ""
                if document.name.lower().endswith(".pdf"):
                    with fitz.open(temp_path) as doc:
                        for page in doc:
                            text += page.get_text()
                elif document.name.lower().endswith((".jpg", ".jpeg", ".png")):
                    img = Image.open(temp_path).convert("L")
                    text = pytesseract.image_to_string(img, config="--oem 3 --psm 6")

                # Extract and persist
                result = extract_document(text)
                doc_type = result.get("Document Type", "Unknown")
                # Ensure saved doc_type aligns with model choices
                from .models import UploadedDocument as UDModel
                valid_types = {c[0] for c in UDModel.CATEGORY_CHOICES}
                if doc_type not in valid_types:
                    doc_type = "OTHER"
                stored_data = {k: v for k, v in result.items() if k not in ("Document Type", "Confidence", "_score")}

                uploaded = UploadedDocument.objects.create(
                    user=request.user,
                    file=document,
                    file_hash=file_hash,
                    doc_type=doc_type,
                    extracted_data=stored_data,
                )
                last_uploaded = uploaded
                processed += 1

                if not unlimited:
                    profile.tokens -= 1
                    profile.save()

                UsageLog.objects.create(
                    user=request.user, doc_type=doc_type, tokens_used=0 if unlimited else 1, action="document processed"
                )
                logger.info(f"Document processed: {doc_type} by {request.user.username}")
                
                # Cleanup temp file
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception as e:
                    logger.warning(f"Temp file cleanup failed: {e}")

            if duplicates:
                messages.warning(request, f"⚠️ {len(duplicates)} duplicate file(s) detected. Skipped processing and kept previous results.")
            if processed > 1:
                messages.success(request, f"✅ Processed {processed} documents successfully.")
                return redirect("history")
            elif processed == 1 and last_uploaded:
                messages.success(request, f"✅ {last_uploaded.doc_type} processed successfully!")
                return redirect("document_detail", doc_id=last_uploaded.id)
            elif processed == 0 and last_uploaded:
                messages.info(request, "ℹ️ Duplicate detected. Showing existing result.")
                return redirect("document_detail", doc_id=last_uploaded.id)

    # ---------------- History ----------------
    docs = UploadedDocument.objects.filter(user=request.user).order_by("-uploaded_at")

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    if start_date:
        docs = docs.filter(uploaded_at__date__gte=parse_date(start_date))
    if end_date:
        docs = docs.filter(uploaded_at__date__lte=parse_date(end_date))

    doc_type_filter = request.GET.get("doc_type")
    if doc_type_filter:
        docs = docs.filter(doc_type=doc_type_filter)

    # Exports
    if request.GET.get("export") == "csv":
        return export_csv(docs)
    if request.GET.get("export") == "excel":
        return export_excel(docs)

    stats = docs.values("doc_type").annotate(total=Count("id"))
    # Token metrics
    used_tokens = UsageLog.objects.filter(user=request.user).aggregate(total=Count("id"))['total'] or 0
    total_tokens = profile.tokens + used_tokens
    token_percent = int((profile.tokens / total_tokens) * 100) if total_tokens else 100

    context.update({
        "documents": docs,
        "history": docs,
        "doc_types": UploadedDocument.objects.filter(user=request.user).values_list("doc_type", flat=True).distinct(),
        "stats": stats,
        "remaining_tokens": profile.tokens,
        "used_tokens": used_tokens,
        "total_tokens": total_tokens,
        "token_percent": token_percent,
        "show_upgrade": profile.tokens < 3,
    })
    return render(request, "extractor/home.html", context)


@login_required
def history(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    docs = UploadedDocument.objects.filter(user=request.user).order_by("-uploaded_at")

    # Filters
    q = request.GET.get("q")
    doc_type = request.GET.get("type")
    start = request.GET.get("start")
    end = request.GET.get("end")
    min_conf = request.GET.get("min_conf")

    if q:
        docs = docs.filter(Q(file__icontains=q) | Q(doc_type__icontains=q))
    if doc_type:
        docs = docs.filter(doc_type=doc_type)
    if start:
        docs = docs.filter(uploaded_at__date__gte=start)
    if end:
        docs = docs.filter(uploaded_at__date__lte=end)
    if min_conf:
        try:
            docs = docs.filter(confidence__gte=float(min_conf))
        except ValueError:
            pass

    return render(request, "extractor/history.html", {
        "documents": docs,
        "remaining_tokens": profile.tokens,
        "q": q or "",
        "type": doc_type or "",
        "start": start or "",
        "end": end or "",
        "min_conf": min_conf or "",
    })


@login_required
def compare_docs(request):
    docs = UploadedDocument.objects.filter(user=request.user).order_by("-uploaded_at")
    comp = None
    a = b = None
    if request.method == "POST":
        a_id = request.POST.get("doc_a")
        b_id = request.POST.get("doc_b")
        if a_id and b_id and a_id != b_id:
            a = get_object_or_404(UploadedDocument, id=a_id, user=request.user)
            b = get_object_or_404(UploadedDocument, id=b_id, user=request.user)
            keys = sorted(set(list((a.extracted_data or {}).keys()) + list((b.extracted_data or {}).keys())))
            rows = []
            for k in keys:
                va = (a.extracted_data or {}).get(k)
                vb = (b.extracted_data or {}).get(k)
                va_val = va.get("value") if isinstance(va, dict) else va
                vb_val = vb.get("value") if isinstance(vb, dict) else vb
                rows.append({"field": k, "a": va_val, "b": vb_val, "diff": va_val != vb_val})
            comp = {"a": a, "b": b, "rows": rows}
    return render(request, "extractor/compare.html", {"documents": docs, "comparison": comp})


# ------------------ INDIVIDUAL DOCUMENT VIEW ------------------
@login_required
def document_detail(request, doc_id):
    """View full extracted result for a single document."""
    doc = get_object_or_404(UploadedDocument, id=doc_id, user=request.user)
    # Rebuild a result-like object to feed insights using stored data
    raw = doc.extracted_data or {}
    # Flatten any legacy structures like {"value": X, "confidence": Y}
    flat = {}
    for k, v in raw.items():
        if isinstance(v, dict) and "value" in v:
            flat[k] = v.get("value")
        else:
            flat[k] = v
    result_like = {"Document Type": doc.doc_type, **flat}
    insights = generate_ai_insights(result_like)
    data = flat
    resume = {
        "is_resume": any(k in data for k in ["Candidate Name", "Skills", "Education", "Experience"]),
        "candidate_name": data.get("Candidate Name"),
        "email": data.get("Email"),
        "phone": data.get("Phone"),
        "skills": data.get("Skills"),
        "education_items": data.get("Education Items"),
        "education": data.get("Education"),
        "experience": data.get("Experience"),
        "experience_years": data.get("Experience Years"),
    }
    return render(
        request,
        "extractor/document_detail.html",
        {"document": doc, "extracted_data": data, "insights": insights, "resume": resume},
    )


# ------------------ EXPORT HELPERS ------------------
def export_csv(docs):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="documents.csv"'
    writer = csv.writer(response)
    writer.writerow(["ID", "Doc Type", "Uploaded At", "Extracted Data"])
    for d in docs:
        writer.writerow([d.id, d.doc_type, d.uploaded_at, d.extracted_data])
    return response


def export_excel(docs):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Extracted Documents"
    ws.append(["ID", "Doc Type", "Uploaded At", "Extracted Data"])
    for d in docs:
        ws.append([d.id, d.doc_type, d.uploaded_at.strftime("%Y-%m-%d %H:%M"), str(d.extracted_data)])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="documents.xlsx"'
    wb.save(response)
    return response


# ------------------ PER-DOCUMENT DOWNLOADS ------------------
@login_required
def download_json(request, doc_id):
    doc = get_object_or_404(UploadedDocument, id=doc_id, user=request.user)
    from django.http import JsonResponse
    return JsonResponse(doc.extracted_data or {}, json_dumps_params={"indent": 2})


@login_required
def download_csv(request, doc_id):
    doc = get_object_or_404(UploadedDocument, id=doc_id, user=request.user)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="document_{doc.id}.csv"'
    writer = csv.writer(response)
    writer.writerow(["Field", "Value"]) 
    data = doc.extracted_data or {}
    for key, value in data.items():
        # value may be object with 'value' key or plain
        if isinstance(value, dict) and "value" in value:
            writer.writerow([key, value.get("value", "")])
        else:
            writer.writerow([key, value])
    return response
