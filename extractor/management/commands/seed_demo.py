from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from extractor.models import UploadedDocument
import random


class Command(BaseCommand):
	help = "Seed demo documents for all users"

	def handle(self, *args, **options):
		doc_types = ["PAN", "AADHAAR", "GST", "FSSAI", "UDYAM"]
		count_created = 0
		for user in User.objects.all():
			for i in range(6):
				dt = random.choice(doc_types)
				conf = random.randint(55, 98)
				data = {
					"Name": {"value": f"Demo User {i}", "confidence": random.randint(70, 95)},
					"Date of Birth": {"value": "1999-01-0" + str((i % 9) + 1), "confidence": random.randint(60, 90)},
					"Address": {"value": f"Street {i}, City", "confidence": random.randint(60, 90)}
				}
				UploadedDocument.objects.create(
					user=user,
					file="uploads/demo.pdf",
					file_hash=f"demo_{user.id}_{i}",
					doc_type=dt,
					extracted_data=data,
					confidence=conf,
				)
				count_created += 1
		self.stdout.write(self.style.SUCCESS(f"Seeded {count_created} demo documents."))
