from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Set onboarding_completed=True for all users'

    def handle(self, *args, **options):
        count = 0
        for user in User.objects.all():
            if hasattr(user, 'profile'):
                if not user.profile.onboarding_completed:
                    user.profile.onboarding_completed = True
                    user.profile.save()
                    count += 1
                    self.stdout.write(f'✅ Updated: {user.email}')
        
        self.stdout.write(self.style.SUCCESS(f'\n🎉 Completed! Updated {count} users.'))