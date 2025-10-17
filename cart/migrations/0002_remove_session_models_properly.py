# Generated to properly remove cart session models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cart', '0001_initial'),
    ]

    operations = [
        # Step 1: Remove foreign key constraints first
        migrations.RemoveField(
            model_name='cartsessionitem',
            name='cart_session',
        ),
        migrations.RemoveField(
            model_name='cartsessionitem', 
            name='product',
        ),
        migrations.RemoveField(
            model_name='wishlistitem',
            name='product',
        ),
        migrations.RemoveField(
            model_name='wishlistitem',
            name='user',
        ),
        
        # Step 2: Remove unique constraints
        migrations.AlterUniqueTogether(
            name='cartsessionitem',
            unique_together=None,
        ),
        migrations.AlterUniqueTogether(
            name='wishlistitem',
            unique_together=None,
        ),
        
        # Step 3: Delete models (this will drop tables)
        migrations.DeleteModel(name='CartSessionItem'),
        migrations.DeleteModel(name='WishlistItem'), 
        migrations.DeleteModel(name='CartSession'),
    ]