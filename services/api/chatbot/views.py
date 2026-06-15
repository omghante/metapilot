from django.shortcuts import render
from django.views import View

class ChatbotTestPageView(View):
    def get(self, request):
        return render(request, 'chatbot/test_page.html')
