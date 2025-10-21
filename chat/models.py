from django.db import models
from django.conf import settings
import uuid


class ChatMessage(models.Model):
    # Allow null user so anonymous/guest messages can be stored
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    # Per-message anonymous id (falls back to user's anonymous_id when available)
    anonymous_id = models.UUIDField(default=uuid.uuid4, editable=False)
    message = models.TextField()
    # Channel indicates which role/category the message belongs to.
    CHANNEL_CHOICES = [
        ('chat_smart_seller', 'Smart Seller'),
        ('chat_smart_buyer_shopkeeper', 'Smart Buyer - Shopkeeper'),
        ('chat_smart_buyer_mandi_owner', 'Smart Buyer - Mandi Owner'),
        ('chat_smart_buyer_community', 'Smart Buyer - Community'),
    ]
    channel = models.CharField(max_length=64, choices=CHANNEL_CHOICES, null=True, blank=True, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.user} ({self.channel}) @ {self.timestamp}: {self.message[:50]}"
