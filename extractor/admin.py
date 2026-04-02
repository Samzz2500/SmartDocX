from django.contrib import admin
from .models import UploadedDocument, UsageLog, SubscriptionPlan, Profile

@admin.register(UploadedDocument)
class UploadedDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "doc_type", "confidence", "uploaded_at")
    list_filter = ("doc_type",)
    search_fields = ("user__username", "doc_type")

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "tokens", "subscription_plan", "subscription_expiry")

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "tokens", "duration_days")

@admin.register(UsageLog)
class UsageLogAdmin(admin.ModelAdmin):
    list_display = ("user", "doc_type", "tokens_used", "action", "created_at")
