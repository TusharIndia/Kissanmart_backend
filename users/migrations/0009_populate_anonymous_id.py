from django.db import migrations, models
import uuid


def generate_anonymous_ids(apps, schema_editor):
    CustomUser = apps.get_model('users', 'CustomUser')
    # 1) Assign anonymous_id where null
    for user in CustomUser.objects.filter(anonymous_id__isnull=True):
        user.anonymous_id = uuid.uuid4()
        user.save(update_fields=['anonymous_id'])

    # 2) Detect and resolve duplicates (keep the first row for each value,
    #    assign new UUIDs to the others). This prevents unique index creation
    #    from failing if multiple rows accidentally share the same UUID.
    from django.db.models import Count

    duplicated_values = (
        CustomUser.objects
        .values('anonymous_id')
        .exclude(anonymous_id__isnull=True)
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
    )

    for entry in duplicated_values:
        anon_value = entry['anonymous_id']
        users_with_value = CustomUser.objects.filter(anonymous_id=anon_value).order_by('id')
        # keep the first one, change the rest
        first = None
        for u in users_with_value:
            if first is None:
                first = u
                continue
            u.anonymous_id = uuid.uuid4()
            u.save(update_fields=['anonymous_id'])


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
