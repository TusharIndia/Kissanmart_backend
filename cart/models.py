from django.db import models
from django.contrib.auth import get_user_model
from products.models import Product
from decimal import Decimal
import uuid

User = get_user_model()


class Cart(models.Model):
    """
    User's shopping cart - one cart per user
    """
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='cart',
        help_text="The user who owns this cart"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = "Shopping Cart"
        verbose_name_plural = "Shopping Carts"
    
    def __str__(self):
        return f"Cart for {self.user.get_identifier()}"
    
    @property
    def total_items(self):
        """Get total number of items in cart"""
        return self.items.aggregate(
            total=models.Sum('quantity')
        )['total'] or 0
    
    @property
    def total_amount(self):
        """Calculate total amount for all items in cart"""
        total = Decimal('0.00')
        for item in self.items.all():
            total += item.subtotal
        return total
    
    @property
    def items_count(self):
        """Get number of different products in cart"""
        return self.items.count()
    
    def clear(self):
        """Remove all items from cart"""
        self.items.all().delete()
        self.save()


class CartItem(models.Model):
    """
    Individual items in a user's cart
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cart = models.ForeignKey(
        Cart, 
        on_delete=models.CASCADE, 
        related_name='items',
        help_text="The cart this item belongs to"
    )
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='cart_items',
        help_text="The product being added to cart"
    )
    quantity = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=1,
        help_text="Quantity of the product"
    )
    unit_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Price per unit at the time of adding to cart"
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-added_at']
        unique_together = ('cart', 'product')
        verbose_name = "Cart Item"
        verbose_name_plural = "Cart Items"
    
    def __str__(self):
        return f"{self.quantity} x {self.product.title} in {self.cart.user.get_identifier()}'s cart"
    
    def save(self, *args, **kwargs):
        # Set unit price from product if not already set
        if not self.unit_price:
            self.unit_price = self.product.price_per_unit
        super().save(*args, **kwargs)
        # Update cart's updated_at timestamp
        self.cart.save()
    
    def delete(self, *args, **kwargs):
        cart = self.cart
        super().delete(*args, **kwargs)
        # Update cart's updated_at timestamp
        cart.save()
    
    @property
    def subtotal(self):
        """Calculate subtotal for this cart item"""
        return self.quantity * self.unit_price
    
    @property
    def is_available(self):
        """Check if the product is still available and published"""
        return (
            self.product.is_published and 
            self.product.quantity_available >= self.quantity
        )
    
    @property
    def availability_status(self):
        """Get availability status message"""
        if not self.product.is_published:
            return "Product no longer available"
        elif self.product.quantity_available < self.quantity:
            return f"Only {self.product.quantity_available} {self.product.unit} available"
        else:
            return "Available"



