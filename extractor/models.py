from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now, timedelta


# ---------------- Subscription Plans ----------------
class SubscriptionPlan(models.Model):
    """Different token-based subscription tiers."""
    name = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    tokens = models.IntegerField()
    duration_days = models.IntegerField(default=30)  # plan validity in days

    def __str__(self):
        return f"{self.name} - ₹{self.price} - {self.tokens} tokens"


# ---------------- User Profile ----------------
class Profile(models.Model):
    """User profile linked to auth.User."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="extractor_profile")
    tokens = models.IntegerField(default=999999999)  # effectively unlimited for now
    subscription_plan = models.ForeignKey(
        SubscriptionPlan, null=True, blank=True, on_delete=models.SET_NULL
    )
    subscription_expiry = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} ({'Unlimited' if self.tokens > 1000000 else f'{self.tokens} tokens'})"

    def has_active_subscription(self):
        """Check if subscription is active."""
        return self.subscription_expiry and self.subscription_expiry >= now().date()

    def deduct_tokens(self, count: int):
        """Deduct tokens after extraction."""
        if self.tokens > count:
            self.tokens -= count
            self.save()
        else:
            self.tokens = 0
            self.save()


# ---------------- Uploaded Documents ----------------
class UploadedDocument(models.Model):
    """Store uploaded files and their extracted results."""
    CATEGORY_CHOICES = [
        ("GST", "GST"),
        ("PAN", "PAN"),
        ("FSSAI", "FSSAI"),
        ("AADHAAR", "AADHAAR"),
        ("UDYAM", "UDYAM"),
        ("DL", "Driving License"),
        ("RC", "Registration Certificate"),
        ("AGREEMENT", "Agreement"),
        ("AFFIDAVIT", "Affidavit"),
        ("RESUME", "Resume/CV"),
        ("OTHER", "Other"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.FileField(upload_to="uploads/")
    file_hash = models.CharField(max_length=64, unique=False)
    doc_type = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="OTHER")
    extracted_data = models.JSONField(default=dict)
    confidence = models.FloatField(default=0)  # ✅ used for accuracy score
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.doc_type} - {self.user.username}"

    @property
    def short_name(self):
        """Return short file name for display."""
        return self.file.name.split('/')[-1]

    @property
    def is_high_confidence(self):
        """Return True if extraction confidence > 80%."""
        return self.confidence >= 80


# ---------------- Usage Logs ----------------
class UsageLog(models.Model):
    """Token usage + activity tracking."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    doc_type = models.CharField(max_length=50)
    tokens_used = models.IntegerField(default=0)
    action = models.CharField(max_length=100, default="processed")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} | {self.doc_type} | {self.tokens_used} tokens"

    @classmethod
    def log_action(cls, user, doc_type, tokens=1, action="processed"):
        """Helper method to quickly log an extraction action."""
        return cls.objects.create(
            user=user,
            doc_type=doc_type,
            tokens_used=tokens,
            action=action,
        )
