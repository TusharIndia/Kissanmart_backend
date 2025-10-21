from django.urls import path
from .views import ChatMessageListView, ChatMessageCreateView

urlpatterns = [
    path('messages/', ChatMessageListView.as_view(), name='chat-messages'),
    path('messages/create/', ChatMessageCreateView.as_view(), name='chat-create'),
]
