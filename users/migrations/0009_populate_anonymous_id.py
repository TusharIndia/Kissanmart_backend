from django.db import migrations, models
import uuid


def generate_anonymous_ids(apps, schema_editor):
    CustomUser = apps.get_model('users', 'CustomUser')
    for user in CustomUser.objects.filter(anonymous_id__isnull=True):
        user.anonymous_id = uuid.uuid4()
        user.save(update_fields=['anonymous_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_customuser_anonymous_id'),
    ]

    operations = [
        migrations.RunPython(generate_anonymous_ids, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='customuser',
            name='anonymous_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
