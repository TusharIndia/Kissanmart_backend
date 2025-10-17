# Generated manually to add Razorpay fields to Order model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_alter_order_payment_method'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='razorpay_order_id',
            field=models.CharField(blank=True, help_text='Razorpay order ID', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='razorpay_payment_id',
            field=models.CharField(blank=True, help_text='Razorpay payment ID', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='razorpay_signature',
            field=models.CharField(blank=True, help_text='Razorpay payment signature', max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='payment_method',
            field=models.CharField(choices=[('upi', 'UPI'), ('netbanking', 'Net Banking'), ('card', 'Credit/Debit Card'), ('wallet', 'Digital Wallet'), ('cod', 'Cash on Delivery')], help_text='Payment method used', max_length=20),
        ),
    ]