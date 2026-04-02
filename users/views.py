import os, hashlib, fitz
from PIL import Image
import pytesseract
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q, Avg
from django.utils.timezone import now
from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView
from django.urls import reverse
from extractor.models import UploadedDocument, UsageLog, SubscriptionPlan, Profile
from extractor.utils import extract_document
from extractor.validators import validate_file_size, validate_file_type, sanitize_filename
from .forms import UserRegisterForm, FeedbackForm


@login_required
def settings_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return render(request, "users/settings.html", {"profile": profile})


@login_required
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    docs = UploadedDocument.objects.filter(user=request.user).order_by("-uploaded_at")[:5]
    return render(request, "users/profile.html", {"profile": profile, "recent_docs": docs})


def contact(request):
    if not request.user.is_authenticated:
        # allow guests to send feedback by creating an anonymous-like record
        user = None
    if request.method == "POST":
        if request.user.is_authenticated:
            form = FeedbackForm(request.POST)
            if form.is_valid():
                fb = form.save(commit=False)
                fb.user = request.user
                fb.save()
                messages.success(request, "✅ Feedback sent. Thank you!")
                return redirect("contact")
        else:
            messages.error(request, "Please login to send feedback.")
            return redirect("login")
    else:
        form = FeedbackForm()
    return render(request, "users/contact.html", {"form": form})

def landing(request):
    plans = SubscriptionPlan.objects.all()
    return render(request, "landing.html", {"plans": plans})

def register(request):
    """ User registration view """
    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Ensure profile exists
            Profile.objects.get_or_create(user=user)
            login(request, user)
            return redirect("dashboard")
    else:
        form = UserRegisterForm()
    return render(request, "users/register.html", {"form": form})


@login_required
def dashboard(request):
    """ Main dashboard with upload, extraction, history, stats """
    profile = request.user.extractor_profile
    # Graceful subscription expiry handling
    if profile.subscription_expiry and profile.subscription_expiry < now().date():
        profile.subscription_plan = None
        profile.subscription_expiry = None
        profile.save()
    context = {}

    # ----------------- Handle Upload -----------------
    if request.method == "POST":
        document = request.FILES.get("document")
        selected_doc_type = request.POST.get("doc_type")

        if not document:
            messages.error(request, "⚠️ Please upload a file.")
        else:
            # Security: validate and sanitize
            try:
                validate_file_size(document)
                validate_file_type(document)
                safe_name = sanitize_filename(document.name)
            except Exception as e:
                messages.error(request, f"⚠️ {str(e)}")
                return redirect("dashboard")

            temp_dir = os.path.join(settings.MEDIA_ROOT, "temp")
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, safe_name)
            with open(temp_path, "wb+") as f:
                for chunk in document.chunks():
                    f.write(chunk)

            hash_sha256 = hashlib.sha256()
            with open(temp_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            file_hash = hash_sha256.hexdigest()

            existing = UploadedDocument.objects.filter(
                file_hash=file_hash, user=request.user
            ).first()

            if existing:
                messages.warning(request, "⚠️ Duplicate detected, showing old result.")
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
                return redirect("document_detail", doc_id=existing.id)
            else:
                text = ""
                if document.name.lower().endswith(".pdf"):
                    with fitz.open(temp_path) as doc:
                        for page in doc:
                            text += page.get_text()
                elif document.name.lower().endswith((".jpg", ".jpeg", ".png")):
                    img = Image.open(temp_path)
                    text = pytesseract.image_to_string(img)

                extracted_data = extract_document(text)
                doc_type = extracted_data.get("Document Type", selected_doc_type or "OTHER")

                if profile.tokens <= 0 and profile.tokens <= 1000000:
                    messages.error(request, "❌ No tokens left. Please upgrade.")
                else:
                    uploaded = UploadedDocument.objects.create(
                        user=request.user,
                        file=document,
                        file_hash=file_hash,
                        doc_type=doc_type,
                        extracted_data=extracted_data,
                    )
                    unlimited = profile.tokens > 1000000
                    if not unlimited:
                        profile.tokens -= 1
                        profile.save()

                    UsageLog.objects.create(
                        user=request.user, doc_type=doc_type, tokens_used=0 if unlimited else 1
                    )
                    messages.success(request, f"✅ {doc_type} processed!")
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                    return redirect("document_detail", doc_id=uploaded.id)

    # ----------------- Filters & History -----------------
    history = UploadedDocument.objects.filter(user=request.user).order_by("-uploaded_at")

    search_query = request.GET.get("search")
    doc_type_filter = request.GET.get("doc_type")
    date_filter = request.GET.get("date")
    min_conf = request.GET.get("min_conf")

    if search_query:
        history = history.filter(
            Q(file__icontains=search_query) |
            Q(doc_type__icontains=search_query)
        )
    if doc_type_filter:
        history = history.filter(doc_type=doc_type_filter)
    if date_filter:
        history = history.filter(uploaded_at__date=date_filter)
    if min_conf:
        try:
            history = history.filter(confidence__gte=float(min_conf))
        except ValueError:
            pass

    context["history"] = history

    # ----------------- Token & KPI stats -----------------
    unlimited_tokens = profile.tokens and profile.tokens > 1000000
    total_tokens = (profile.subscription_plan.tokens if profile.subscription_plan else 5) if not unlimited_tokens else 0
    used_tokens = (max(total_tokens - profile.tokens, 0) if not unlimited_tokens else 0)
    token_percent = ((profile.tokens / total_tokens) * 100 if total_tokens > 0 else 0) if not unlimited_tokens else 100

    docs_qs = UploadedDocument.objects.filter(user=request.user)
    today = now().date()
    usage_today = docs_qs.filter(uploaded_at__date=today).count()
    usage_month = docs_qs.filter(uploaded_at__year=today.year, uploaded_at__month=today.month).count()
    total_docs = docs_qs.count()
    doc_type_counts = list(docs_qs.values("doc_type").annotate(total=Count("id")))

    # Simple insight strings
    top_type = max(doc_type_counts, key=lambda d: d["total"])['doc_type'] if doc_type_counts else "—"
    insights = {"top_type": top_type}

    recent_activity = UsageLog.objects.filter(user=request.user).order_by('-created_at')[:10]

    context.update({
        "remaining_tokens": profile.tokens,
        "total_tokens": total_tokens,
        "used_tokens": used_tokens,
        "token_percent": round(token_percent, 2),
        "unlimited_tokens": unlimited_tokens,
        "usage_stats": doc_type_counts,
        "usage_today": usage_today,
        "usage_month": usage_month,
        "total_docs": total_docs,
        "insights": insights,
        "recent_activity": recent_activity,
    })

    return render(request, "users/dashboard.html", context)


class PrettyLoginView(LoginView):
    template_name = "users/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse("dashboard")


def logout_view(request):
    """Log out user and redirect to login (allows GET for simplicity)."""
    logout(request)
    return redirect("login")
