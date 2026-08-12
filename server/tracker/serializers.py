# tracker/serializers.py
from rest_framework import serializers
from django.utils.dateparse import parse_datetime
from django.contrib.auth import get_user_model
import json

from .models import RawEvent, Block, TimecardEntry, TaskType, Client, Project

User = get_user_model()


# ========================================
# ========== RAW EVENT SERIALIZER ========
# ========================================
class RawEventSerializer(serializers.ModelSerializer):
    """
    Updated for FK user (AUTH_USER_MODEL).
    """
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    username = serializers.SerializerMethodField(read_only=True)
    ctx = serializers.JSONField(required=False, allow_null=True, default=dict)

    class Meta:
        model = RawEvent
        fields = [
            'id', 'start_ts', 'end_ts', 'app_name', 'bundle_id', 'window_title',
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
        data = dict(data)
        for k in ('app_name', 'bundle_id', 'window_title', 'url', 'file_path', 'hostname'):
            if data.get(k) is not None:
                data[k] = str(data[k]).strip()

        ts_start = data.get('start_ts'); ts_end = data.get('end_ts')
        if isinstance(ts_start, str):
            dt = parse_datetime(ts_start)
            if dt:
                data['start_ts'] = dt
        if isinstance(ts_end, str):
            dt = parse_datetime(ts_end)
            if dt:
                data['end_ts'] = dt
        return super().to_internal_value(data)


# ========================================
# ========== CLIENT SERIALIZER ===========
# ========================================
class ClientSerializer(serializers.ModelSerializer):
    project_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Client
        fields = ['id', 'name', 'code', 'is_active', 'project_count']
        read_only_fields = ['id']
    
    def get_project_count(self, obj):
        return obj.projects.filter(is_active=True).count()


class ClientListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for dropdowns"""
    class Meta:
        model = Client
        fields = ['id', 'name', 'code']


# ========================================
# ========== PROJECT SERIALIZER ==========
# ========================================
class ProjectSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    
    class Meta:
        model = Project
        fields = ['id', 'name', 'client', 'client_name', 'is_active']
        read_only_fields = ['id']


class ProjectListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for dropdowns"""
    class Meta:
        model = Project
        fields = ['id', 'name', 'client']


# ========================================
# ========== TASK TYPE SERIALIZER ========
# ========================================
class TaskTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskType
        fields = [
            'id', 'name', 'code', 'is_billable', 
            'color', 'icon', 'sort_order', 'is_active'
        ]
        read_only_fields = ['id']


class TaskTypeListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for dropdowns"""
    class Meta:
        model = TaskType
        fields = ['id', 'name', 'code', 'color', 'is_billable']


# ========================================
# ========== BLOCK SERIALIZERS ===========
# ========================================
class BlockSerializer(serializers.ModelSerializer):
    """Full block serializer with all relationships"""
    
    # Related object names (read-only)
    client_name = serializers.CharField(source='client.name', read_only=True, allow_null=True)
    project_name = serializers.CharField(source='project.name', read_only=True, allow_null=True)
    task_name = serializers.CharField(source='task.name', read_only=True, allow_null=True)
    task_type_name = serializers.CharField(source='task_type.name', read_only=True, allow_null=True)
    task_type_code = serializers.CharField(source='task_type.code', read_only=True, allow_null=True)
    task_type_color = serializers.CharField(source='task_type.color', read_only=True, allow_null=True)
    task_type_is_billable = serializers.BooleanField(source='task_type.is_billable', read_only=True, allow_null=True)
    
    # AI fields
    ai_extracted_client = serializers.CharField(read_only=True)
    ai_category = serializers.CharField(read_only=True)
    # Sourced from proposed_confidence: the classifier stores its decision
    # confidence there for all states. The legacy Block.ai_confidence field is
    # never written by ClassificationService (stuck at its 0.0 default), so
    # reading it directly always reported 0.0.
    ai_confidence = serializers.FloatField(source='proposed_confidence', read_only=True)
    
    # Misc
    hints = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Block
        fields = [
            # Identity
            "id", "user", "hostname", "device_id",
            
            # Time
            "start", "end", "minutes", "day",
            
            # Activity context
            "title", "window_title", "url", "file_path", "app_name", "bundle_id",
            "description", "attendees", "hints",
            
            # Classification - IDs (for writes)
            "client", "project", "task", "task_type",
            
            # Classification - Names (read-only)
            "client_name", "project_name", "task_name",
            "task_type_name", "task_type_code", "task_type_color", "task_type_is_billable",
            
            # Legacy/computed
            "category_hours", "notes",
            
            # Status flags
            "locked", "is_categorized", "categorized_by", "categorized_at",
            "approved", "approved_at",
            
            # AI metadata
            "ai_extracted_client", "ai_category", "ai_confidence", "ai_processed_at",
        ]
        read_only_fields = [
            "id", "minutes", "day", "user", "hostname", "device_id",
            "client_name", "project_name", "task_name",
            "task_type_name", "task_type_code", "task_type_color", "task_type_is_billable",
            "ai_extracted_client", "ai_category", "ai_confidence", "ai_processed_at",
            "categorized_at", "approved_at",
        ]


class BlockLiteSerializer(serializers.ModelSerializer):
    """Lightweight serializer for lists and AI processing"""
    class Meta:
        model = Block
        fields = [
            "id", "user", "hostname", "start", "end", "minutes", "day",
            "window_title", "url", "file_path", "app_name",
            "client", "project", "task_type",
            "ai_extracted_client", "ai_category", "ai_confidence", "ai_processed_at",
            "is_categorized", "categorized_by",
        ]
        read_only_fields = fields


class BlockCategorizationSerializer(serializers.Serializer):
    """For PATCH requests to categorize blocks"""
    client_id = serializers.IntegerField(required=False, allow_null=True)
    project_id = serializers.IntegerField(required=False, allow_null=True)
    task_type_id = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    
    def validate_client_id(self, value):
        if value:
            if not Client.objects.filter(id=value).exists():
                raise serializers.ValidationError("Client not found")
        return value
    
    def validate_project_id(self, value):
        if value:
            if not Project.objects.filter(id=value).exists():
                raise serializers.ValidationError("Project not found")
        return value
    
    def validate_task_type_id(self, value):
        if value:
            if not TaskType.objects.filter(id=value).exists():
                raise serializers.ValidationError("TaskType not found")
        return value


class BulkCategorizationSerializer(serializers.Serializer):
    """For bulk categorization of multiple blocks"""
    block_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        max_length=100,
    )
    client_id = serializers.IntegerField(required=False, allow_null=True)
    project_id = serializers.IntegerField(required=False, allow_null=True)
    task_type_id = serializers.IntegerField(required=False, allow_null=True)


# ========================================
# ========== TIMECARD SERIALIZER =========
# ========================================
class TimecardEntrySerializer(serializers.ModelSerializer):
    """Full timecard serializer"""
    client_name = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TimecardEntry
        fields = [
            'id', 'date', 'user', 'username', 
            'client', 'client_name', 'project', 'project_name',
            'total_hours', 'category_breakdown', 'activities_summary',
            'confidence_score', 'needs_review', 'status', 
            'reviewed_at', 'notes', 'block_ids'
        ]
        read_only_fields = ['id', 'username']

    def get_client_name(self, obj):
        return getattr(obj.client, 'name', 'Unknown')

    def get_project_name(self, obj):
        return getattr(obj.project, 'name', None)

    def get_username(self, obj):
        return getattr(obj.user, 'username', None)


# ========================================
# ========== GROUPED VIEW SERIALIZER =====
# ========================================
class GroupedBlocksSerializer(serializers.Serializer):
    """
    Serializer for the hybrid grouped view:
    Client → Project → TaskType → Blocks
    """
    
    def to_representation(self, blocks):
        """
        Takes a queryset of blocks and returns grouped structure
        """
        grouped = {}
        
        for block in blocks:
            # Client level
            client_name = block.client.name if block.client else 'Uncategorized'
            client_id = block.client.id if block.client else None
            
            if client_name not in grouped:
                grouped[client_name] = {
                    'client_id': client_id,
                    'client_name': client_name,
                    'total_minutes': 0,
                    'projects': {}
                }
            
            # Project level
            project_name = block.project.name if block.project else 'No Project'
            project_id = block.project.id if block.project else None
            
            if project_name not in grouped[client_name]['projects']:
                grouped[client_name]['projects'][project_name] = {
                    'project_id': project_id,
                    'project_name': project_name,
                    'total_minutes': 0,
                    'task_types': {}
                }
            
            # TaskType level
            task_type_name = block.task_type.name if block.task_type else 'Uncategorized'
            task_type_id = block.task_type.id if block.task_type else None
            task_type_color = block.task_type.color if block.task_type else '#9CA3AF'
            
            if task_type_name not in grouped[client_name]['projects'][project_name]['task_types']:
                grouped[client_name]['projects'][project_name]['task_types'][task_type_name] = {
                    'task_type_id': task_type_id,
                    'task_type_name': task_type_name,
                    'color': task_type_color,
                    'total_minutes': 0,
                    'blocks': []
                }
            
            # Add block
            mins = block.minutes or 0
            grouped[client_name]['projects'][project_name]['task_types'][task_type_name]['blocks'].append({
                'id': block.id,
                'start': block.start.isoformat() if block.start else None,
                'end': block.end.isoformat() if block.end else None,
                'minutes': mins,
                'app_name': block.app_name,
                'window_title': block.window_title,
                'is_categorized': block.is_categorized,
                'categorized_by': block.categorized_by,
            })
            
            # Update totals
            grouped[client_name]['projects'][project_name]['task_types'][task_type_name]['total_minutes'] += mins
            grouped[client_name]['projects'][project_name]['total_minutes'] += mins
            grouped[client_name]['total_minutes'] += mins
        
        # Convert to list sorted by total time
        result = sorted(
            grouped.values(),
            key=lambda x: x['total_minutes'],
            reverse=True
        )
        
        return result