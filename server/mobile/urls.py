from django.urls import path
from . import views

urlpatterns = [
    path('start/',            views.MobileStartView.as_view(),          name='mobile-start'),
    path('stop/',             views.MobileStopView.as_view(),           name='mobile-stop'),
    path('recent/',           views.MobileRecentView.as_view(),         name='mobile-recent'),
    path('ai-suggest/',       views.MobileAISuggestView.as_view(),      name='mobile-ai-suggest'),
    path('voice-parse/',      views.MobileVoiceParseView.as_view(),     name='mobile-voice-parse'),
    path('calendar-suggest/', views.MobileCalendarSuggestView.as_view(),name='mobile-calendar-suggest'),
]