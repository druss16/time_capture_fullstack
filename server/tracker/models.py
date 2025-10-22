from django.db import models
class RawEvent(models.Model):
    ts_utc=models.DateTimeField()
    app_name=models.CharField(max_length=255, blank=True, null=True)
    bundle_id=models.CharField(max_length=255, blank=True, null=True)
    window_title=models.TextField(blank=True, null=True)
    url=models.TextField(blank=True, null=True)
    file_path=models.TextField(blank=True, null=True)
    user=models.CharField(max_length=255, blank=True, null=True)
    hostname=models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        indexes=[models.Index(fields=['ts_utc']), models.Index(fields=['user','hostname'])]
        
class SuggestedBlock(models.Model):
    start=models.DateTimeField()
    end=models.DateTimeField()
    label=models.CharField(max_length=255, blank=True, null=True)
    client=models.CharField(max_length=255, blank=True, null=True)
    engagement=models.CharField(max_length=255, blank=True, null=True)
    task_code=models.CharField(max_length=64, blank=True, null=True)
    description=models.TextField(blank=True, null=True)
    confidence=models.FloatField(default=0.0)
    source_ids=models.JSONField(default=list)
    user=models.CharField(max_length=255, blank=True, null=True)
    hostname=models.CharField(max_length=255, blank=True, null=True)

# --- core master data ---
class Client(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)    # your tenant
    name = models.CharField(max_length=200, unique=False)
    is_active = models.BooleanField(default=True)

class Project(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

class Task(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(max_length=200)
    billable = models.BooleanField(default=True)

# --- classification ---
class Block(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    user = models.CharField(max_length=120)      # “danrussell” from agent
    hostname = models.CharField(max_length=120)
    start = models.DateTimeField()
    end = models.DateTimeField()
    title = models.TextField(blank=True, default="")
    url = models.TextField(blank=True, default="")
    file_path = models.TextField(blank=True, default="")
    # human choices
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL)
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True, default="")
    locked = models.BooleanField(default=False)  # after approval/export

class Suggestion(models.Model):
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="suggestions")
    label_type = models.CharField(max_length=20, choices=[("client","client"),("project","project"),("task","task")])
    value_text = models.CharField(max_length=255)     # human label
    confidence = models.FloatField(default=0.0)
    source = models.CharField(max_length=20, default="rule")   # rule|ml
    created_at = models.DateTimeField(auto_now_add=True)

# --- rules (admin-maintained, first line of automation) ---
class Rule(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    pattern = models.CharField(max_length=500)   # glob/regex for url/title/path
    field = models.CharField(max_length=20, choices=[("client","client"),("project","project"),("task","task")])
    value_text = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=[("contains","contains"),("regex","regex"),("glob","glob")], default="contains")
    active = models.BooleanField(default=True)
