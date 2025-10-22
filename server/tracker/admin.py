from django.contrib import admin
from .models import RawEvent, SuggestedBlock
admin.site.register(RawEvent)
admin.site.register(SuggestedBlock)
