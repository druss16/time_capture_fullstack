"""
Run this in your Django environment:
  python manage.py shell < find_qbo_token.py

Or in Docker:
  docker exec -i <container> python manage.py shell < find_qbo_token.py
"""
import django
from django.apps import apps

print("=" * 60)
print("SCANNING FOR QBO/QUICKBOOKS TOKEN STORAGE")
print("=" * 60)

# Search all models for QBO-related fields
qbo_keywords = ['qbo', 'quickbooks', 'intuit', 'oauth', 'token', 'refresh']
found_models = []

for model in apps.get_models():
    model_name = model.__name__.lower()
    fields = [f.name.lower() for f in model._meta.get_fields()]
    
    for keyword in qbo_keywords:
        if keyword in model_name or any(keyword in f for f in fields):
            found_models.append(model)
            break

if found_models:
    print(f"\nFound {len(found_models)} potentially relevant model(s):\n")
    for model in found_models:
        print(f"  Model: {model.__name__} (app: {model._meta.app_label})")
        print(f"  Table: {model._meta.db_table}")
        print(f"  Fields:")
        for f in model._meta.get_fields():
            print(f"    - {f.name} ({type(f).__name__})")
        
        # Check if there are any records
        try:
            count = model.objects.count()
            print(f"  Records: {count}")
            if count > 0:
                obj = model.objects.first()
                for f in model._meta.get_fields():
                    try:
                        val = getattr(obj, f.name, None)
                        if val is not None and any(k in f.name.lower() for k in qbo_keywords):
                            # Mask sensitive values
                            val_str = str(val)
                            if len(val_str) > 20:
                                val_str = val_str[:10] + "..." + val_str[-5:]
                            print(f"    {f.name} = {val_str}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"  (Could not query: {e})")
        print()
else:
    print("\nNo QBO-related models found. Checking settings...")

# Check settings for QBO config
from django.conf import settings
qbo_settings = {}
for attr in dir(settings):
    if any(k in attr.lower() for k in ['qbo', 'quickbooks', 'intuit']):
        val = getattr(settings, attr, None)
        if isinstance(val, str) and len(val) > 20:
            val = val[:10] + "..." + val[-5:]
        qbo_settings[attr] = val

if qbo_settings:
    print("\nQBO-related settings found:")
    for k, v in qbo_settings.items():
        print(f"  {k} = {v}")
else:
    print("\nNo QBO-related settings found in Django settings.")

print("\n" + "=" * 60)