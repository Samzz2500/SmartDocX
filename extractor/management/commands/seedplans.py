from django.core.management.base import BaseCommand
from extractor.models import SubscriptionPlan

class Command(BaseCommand):
    help = "Seed default subscription plans"

    def handle(self, *args, **kwargs):
        plans = [
            {"name": "Basic", "price": 99, "tokens": 50, "duration_days": 30},
            {"name": "Pro", "price": 299, "tokens": 200, "duration_days": 90},
            {"name": "Enterprise", "price": 999, "tokens": 1000, "duration_days": 365},
        ]

        for p in plans:
            SubscriptionPlan.objects.update_or_create(name=p["name"], defaults=p)

        self.stdout.write(self.style.SUCCESS("✅ Subscription plans seeded!"))
