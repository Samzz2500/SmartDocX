from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from extractor.models import Profile  # use the extractor Profile


class Feedback(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="feedbacks")
    subject = models.CharField(max_length=150)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.subject[:20]}"

# ⚡ No need to redefine Profile here, we’ll reuse extractor.models.Profile

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
    else:
        Profile.objects.get_or_create(user=instance)
