from django.urls import path
from chatbot import api_views
from chatbot.views import ChatbotTestPageView

urlpatterns = [
    path('test-ui/', ChatbotTestPageView.as_view(), name='chatbot-test-ui'),
    path('test/', api_views.ChatbotTestView.as_view(), name='chatbot-test'),
    path('check/', api_views.ChatbotQuestionCheckView.as_view(), name='chatbot-check'),
]
