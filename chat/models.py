from django.db import models
from django.conf import settings
import uuid


class ChatMessage(models.Model):
    # Allow null user so anonymous/guest messages can be stored
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    # Per-message anonymous id (falls back to user's anonymous_id when available)
    anonymous_id = models.UUIDField(default=uuid.uuid4, editable=False)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.user} @ {self.timestamp}: {self.message[:50]}"
