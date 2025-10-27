from rest_framework import serializers
from .models import RawEvent, SuggestedBlock, Block, TimecardEntry

class RawEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RawEvent
        fields = '__all__'

class SuggestedBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuggestedBlock
        fields = '__all__'

class BlockSerializer(serializers.ModelSerializer):
    client = serializers.SerializerMethodField()
    project = serializers.SerializerMethodField()
    task = serializers.SerializerMethodField()

    class Meta:
        model = Block
        fields = ['id','start','end','minutes','day','title','window_title','url','file_path',
                  'description','attendees','category_hours','notes','client','project','task','locked']

    def get_client(self, obj): return getattr(obj.client, 'name', None)
    def get_project(self, obj): return getattr(obj.project, 'name', None)
    def get_task(self, obj): return getattr(obj.task, 'name', None)

class TimecardEntrySerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()

    class Meta:
        model = TimecardEntry
        fields = ['id','date','user','client_name','project_name','total_hours',
                  'category_breakdown','activities_summary','confidence_score',
                  'needs_review','status','reviewed_at','notes','block_ids']

    def get_client_name(self, obj): return getattr(obj.client, 'name', 'Unknown')
    def get_project_name(self, obj): return getattr(obj.project, 'name', None)

