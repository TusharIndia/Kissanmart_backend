# Generated to properly remove cart session models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cart', '0001_initial'),
    ]

    operations = [
        # Delete models directly - Django will handle constraints and fields automatically
        migrations.DeleteModel(name='CartSessionItem'),
        migrations.DeleteModel(name='WishlistItem'), 
        migrations.DeleteModel(name='CartSession'),
    ]