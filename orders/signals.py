"""
Signals for handling order-related product quantity updates
"""

from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import transaction
from decimal import Decimal

from .models import Order, OrderItem
from products.models import Product


@receiver(post_save, sender=OrderItem)
def update_product_quantity_on_order_item_save(sender, instance, created, **kwargs):
    """
    Automatically reduce product quantity when order item is created or updated
    """
    if created:
        # New order item created - reduce product quantity
        with transaction.atomic():
            product = Product.objects.select_for_update().get(id=instance.product.id)
            
            if product.quantity_available >= instance.quantity:
                product.quantity_available -= instance.quantity
                product.save(update_fields=['quantity_available'])
            else:
                # This shouldn't happen if validation is working correctly
                # but we'll handle it gracefully
                raise ValueError(f"Insufficient quantity available for {product.title}")


@receiver(post_delete, sender=OrderItem)
def restore_product_quantity_on_order_item_delete(sender, instance, **kwargs):
    """
    Restore product quantity when order item is deleted
    """
    with transaction.atomic():
        try:
            product = Product.objects.select_for_update().get(id=instance.product.id)
            product.quantity_available += instance.quantity
            product.save(update_fields=['quantity_available'])
        except Product.DoesNotExist:
            # Product might have been deleted, ignore
            pass


@receiver(pre_save, sender=Order)
def track_order_status_changes(sender, instance, **kwargs):
    """
    Track order status changes to handle quantity restoration
    """
    if instance.pk:  # Only for existing orders
        try:
            old_instance = Order.objects.get(pk=instance.pk)
            instance._old_status = old_instance.status
        except Order.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender=Order)
def handle_order_status_changes(sender, instance, created, **kwargs):
    """
    Handle product quantity changes based on order status
    """
    if not created and hasattr(instance, '_old_status'):
        old_status = instance._old_status
        new_status = instance.status
        
        # If order is cancelled and wasn't cancelled before, restore product quantities
        if new_status == 'cancelled' and old_status != 'cancelled':
            
            with transaction.atomic():
                for item in instance.items.all():
                    try:
                        product = Product.objects.select_for_update().get(id=item.product.id)
                        product.quantity_available += item.quantity
                        product.save(update_fields=['quantity_available'])
                    except Product.DoesNotExist:
                        # Product might have been deleted, continue with others
                        continue


@receiver(pre_save, sender=OrderItem)
def handle_order_item_quantity_changes(sender, instance, **kwargs):
    """
    Handle quantity changes in order items (in case of updates)
    """
    if instance.pk:  # Only for updates
        try:
            old_instance = OrderItem.objects.get(pk=instance.pk)
            quantity_difference = instance.quantity - old_instance.quantity
            
            if quantity_difference != 0:
                with transaction.atomic():
                    product = Product.objects.select_for_update().get(id=instance.product.id)
                    
                    if quantity_difference > 0:
                        # Quantity increased - reduce product availability
                        if product.quantity_available >= quantity_difference:
                            product.quantity_available -= quantity_difference
                        else:
                            raise ValueError(f"Insufficient quantity available for {product.title}")
                    else:
                        # Quantity decreased - increase product availability
                        product.quantity_available += abs(quantity_difference)
                    
                    product.save(update_fields=['quantity_available'])
                    
        except OrderItem.DoesNotExist:
            # This is a new item, will be handled by post_save
            pass