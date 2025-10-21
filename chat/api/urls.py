from django.urls import path
from .views import ChatMessageListView, ChatMessageCreateView, ChatMessageChannelView

urlpatterns = [
    path('messages/', ChatMessageListView.as_view(), name='chat-messages'),
    path('messages/create/', ChatMessageCreateView.as_view(), name='chat-create'),
    path('messages/channel/', ChatMessageChannelView.as_view(), name='chat-channel'),
]
