# tracker/serializers.py
from rest_framework import serializers
from django.utils.dateparse import parse_datetime
from django.contrib.auth import get_user_model
import json

from .models import RawEvent, Block, TimecardEntry

User = get_user_model()


class RawEventSerializer(serializers.ModelSerializer):
    """
    Updated for FK user (AUTH_USER_MODEL).
    - Write with user (PK) as usual.
    - Expose read-only `username` for convenience.
    - Keep ctx size/shape guards.
    """
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    username = serializers.SerializerMethodField(read_only=True)
    ctx = serializers.JSONField(required=False, allow_null=True, default=dict)

    class Meta:
        model  = RawEvent
        fields = [
            'id', 'ts_utc', 'app_name', 'bundle_id', 'window_title',
            'url', 'file_path', 'user', 'username', 'hostname', 'ctx'
        ]
        read_only_fields = ['id', 'username']

    def get_username(self, obj):
        return getattr(obj.user, "username", None)

    def validate_ctx(self, value):
        if value in (None, serializers.empty):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("ctx must be a JSON object.")
        try:
            raw = json.dumps(value, ensure_ascii=False)
        except Exception as e:
            raise serializers.ValidationError(f"ctx is not serializable: {e}")
        if len(raw) > 50_000:
            raise serializers.ValidationError("ctx too large (>50KB).")
        return value

    def to_internal_value(self, data):
        # Normalize common strings (do NOT touch 'user' now that it's an FK)
        data = dict(data)
        for k in ('app_name','bundle_id','window_title','url','file_path','hostname'):
            if data.get(k) is not None:
                data[k] = str(data[k]).strip()

        ts = data.get('ts_utc')
        if isinstance(ts, str):
            dt = parse_datetime(ts)
            if dt:
                data['ts_utc'] = dt
        return super().to_internal_value(data)



class BlockSerializer(serializers.ModelSerializer):
    client = serializers.SerializerMethodField()
    project = serializers.SerializerMethodField()
    task = serializers.SerializerMethodField()
    hints = serializers.JSONField(required=False, allow_null=True)

    ai_extracted_client = serializers.CharField(read_only=True)
    ai_category = serializers.CharField(read_only=True)
    ai_confidence = serializers.FloatField(read_only=True)

    class Meta:
        model = Block
        fields = [
            "id", "start", "end", "minutes", "day", "title", "window_title",
            "url", "file_path", "description", "attendees", "category_hours",
            "notes", "client", "project", "task", "locked", "hints",
            "ai_extracted_client", "ai_category", "ai_confidence"
        ]
        read_only_fields = ["id", "minutes", "day"]

    def get_client(self, obj):
        return getattr(obj.client, "name", None) or getattr(obj, "ai_extracted_client", None)

    def get_project(self, obj):
        return getattr(obj.project, "name", None)

    def get_task(self, obj):
        return getattr(obj.task, "name", None) or getattr(obj, "ai_category", None)


class TimecardEntrySerializer(serializers.ModelSerializer):
    """
    Matches your UI shape, but now the underlying user is an FK.
    - Expose read-only `username`
    - Keep client_name / project_name helpers
    """
    client_name = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TimecardEntry
        fields = [
            'id','date','user','username','client_name','project_name','total_hours',
            'category_breakdown','activities_summary','confidence_score',
            'needs_review','status','reviewed_at','notes','block_ids'
        ]
        read_only_fields = ['id','username']

    def get_client_name(self, obj):
        return getattr(obj.client, 'name', 'Unknown')

    def get_project_name(self, obj):
        return getattr(obj.project, 'name', None)

    def get_username(self, obj):
        return getattr(obj.user, 'username', None)

# add/extend this
from rest_framework import serializers
from .models import Block

class BlockLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = [
            "id", "user", "hostname", "start", "end",
            "window_title", "url", "file_path",
            "ai_extracted_client", "ai_category", "ai_confidence", "ai_processed_at",
        ]
        read_only_fields = fields