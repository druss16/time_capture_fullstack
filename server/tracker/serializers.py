from rest_framework import serializers
from .models import RawEvent, SuggestedBlock
class RawEventSerializer(serializers.ModelSerializer):
    class Meta: model=RawEvent; fields='__all__'
class SuggestedBlockSerializer(serializers.ModelSerializer):
    class Meta: model=SuggestedBlock; fields='__all__'
