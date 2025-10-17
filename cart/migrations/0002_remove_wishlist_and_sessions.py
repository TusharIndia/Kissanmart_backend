# Generated manually to remove wishlist and cart session tables
from django.db import migrations


def check_and_drop_tables(apps, schema_editor):
    """
    Safely drop tables only if they exist
    """
    db_alias = schema_editor.connection.alias
    with schema_editor.connection.cursor() as cursor:
        # Check if we're using SQLite or PostgreSQL and adjust accordingly
        if 'sqlite' in schema_editor.connection.vendor:
            # For SQLite
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cart_wishlistitem';")
            if cursor.fetchone():
                cursor.execute("DROP TABLE cart_wishlistitem;")
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cart_cartsessionitem';")
            if cursor.fetchone():
                cursor.execute("DROP TABLE cart_cartsessionitem;")
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cart_cartsession';")
            if cursor.fetchone():
                cursor.execute("DROP TABLE cart_cartsession;")
        else:
            # For PostgreSQL and other databases
            cursor.execute("DROP TABLE IF EXISTS cart_wishlistitem CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS cart_cartsessionitem CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS cart_cartsession CASCADE;")


def reverse_operation(apps, schema_editor):
    # No reverse operation needed
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('cart', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(check_and_drop_tables, reverse_operation),
    ]
