from django.db import models
from django.contrib.auth import get_user_model
from PIL import Image
import uuid
from django.db.models import JSONField

# Get the custom user model (or default User if not customized)
User = get_user_model()

# Choices for the quantity unit
UNIT_CHOICES = (
    ('KG', 'Kilogram'),
    ('QUINTAL', 'Quintal (100 Kg)'),
    ('TON', 'Metric Ton'),
    ('DOZEN', 'Dozen'),
    ('UNIT', 'Per Piece/Unit'),
)


class Category(models.Model):
    """Product categories like Fruits, Vegetables, Grains, etc."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Main model for a seller's produce listing.
    """
    # 1. Backend/Auth Fields
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='products', help_text="The user who created this listing.")
    is_published = models.BooleanField(default=True, help_text="Set to False to unlist the product.")
    # compatibility UUID used by API serializers/urls
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    
    # 2. Product Information
    title = models.CharField(max_length=100, default='Unnamed Product', help_text="Name of the produce (e.g., Tomato).")
    category = models.CharField(max_length=100, blank=True, null=True, help_text="High-level crop category (Vegetable, Fruit, etc.).")
    crop = models.CharField(max_length=100, blank=True, null=True, help_text="Specific crop name (e.g., Brinjal).")
    variety = models.CharField(max_length=100, blank=True, null=True, help_text="Specific variety (e.g., Heirloom Tomato).")
    grade = models.CharField(max_length=50, blank=True, null=True, help_text="Grade/quality (e.g., A, B).")
    description = models.TextField(default='', help_text="Detailed description, quality, and farming methods.")
    pexels_image_url = models.URLField(blank=True, null=True, help_text="Image URL fetched from Pexels API based on product title.")
    
    # 3. Pricing & Quantity
    quantity_available = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Total quantity available for sale.")
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default='KG', help_text="The unit of measurement (e.g., KG, Quintal).")
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Price in Rupees per unit.")
    min_order_quantity = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Optional minimum quantity a buyer must order.")
    # compatibility JSON fields expected by API serializers
    mandi_price_reference = JSONField(null=True, blank=True, default=dict)
    buyer_category_visibility = JSONField(null=True, blank=True, default=list)
    # Additional fields expected by API/serializers
    price_currency = models.CharField(max_length=10, blank=True, null=True)
    price_type = models.CharField(max_length=50, blank=True, null=True)
    market_price_source = models.CharField(max_length=255, blank=True, null=True)
    metadata = JSONField(null=True, blank=True, default=dict)
    # Location fields
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True, help_text="City where the product is located")
    pincode = models.CharField(max_length=20, blank=False, null=False, help_text="Pincode where the product is located")
    
    # 4. Target Buyers
    target_mandi_owners = models.BooleanField(default=False, help_text="Target Mandi Owners/Wholesalers.")
    target_shopkeepers = models.BooleanField(default=False, help_text="Target Shopkeepers/Local Retailers.")
    target_communities = models.BooleanField(default=False, help_text="Target Community Groups/Cooperatives.")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.seller.username})"

    @property
    def total_value(self):
        """Calculate total value of available stock"""
        return self.price_per_unit * self.quantity_available

    @property
    def status(self):
        """Determine product status based on availability"""
        if not self.is_published:
            return 'inactive'
        elif self.quantity_available <= 0:
            return 'sold_out'
        else:
            return 'active'

    def soft_delete(self):
        """Soft-delete: keep row but mark unpublished and set a deleted flag via is_published."""
        self.is_published = False
        self.save(update_fields=['is_published'])

    # Compatibility properties to support older serializer names
    @property
    def available_quantity(self):
        return self.quantity_available

    @available_quantity.setter
    def available_quantity(self, val):
        self.quantity_available = val

    @property
    def quantity_unit(self):
        return self.unit

    @quantity_unit.setter
    def quantity_unit(self, val):
        self.unit = val

    @property
    def target_buyers_display(self):
        """Get display string for target buyers"""
        targets = []
        if self.target_mandi_owners:
            targets.append('Mandi Owners')
        if self.target_shopkeepers:
            targets.append('Shopkeepers')
        if self.target_communities:
            targets.append('Communities')
        return ', '.join(targets) if targets else 'All Buyers'
    

def product_image_upload_path(instance, filename):
    """Generate upload path using product name and date"""
    # Clean product name for use in file path
    product_name = instance.product.title
    # Remove special characters and spaces, replace with underscores
    import re
    clean_name = re.sub(r'[^\w\s-]', '', product_name)
    clean_name = re.sub(r'[-\s]+', '_', clean_name)
    clean_name = clean_name.lower()
    
    # Get file extension
    import os
    name, ext = os.path.splitext(filename)
    
    # Create path: product_images/{year}/{month}/{product_name}/{filename}
    from datetime import datetime
    now = datetime.now()
    return f'product_images/{now.year:04d}/{now.month:02d}/{clean_name}/{filename}'


class ProductImage(models.Model):
    """
    Model to handle multiple images for a product.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=product_image_upload_path, blank=True, null=True)
    url = models.URLField(blank=True, null=True, help_text="URL of the image if stored remotely")
    is_primary = models.BooleanField(default=False, help_text="Mark this as the primary image")
    caption = models.CharField(max_length=255, blank=True)
    
    class Meta:
        verbose_name_plural = "Product Images"
        
    def __str__(self):
        return f"Image for {self.product.title}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        
        # Resize image if it exists
        if self.image:
            self.resize_image(self.image.path)

    def resize_image(self, image_path, max_size=(800, 800)):
        """Resize image to optimize storage"""
        try:
            with Image.open(image_path) as img:
                if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    img.save(image_path, optimize=True, quality=85)
        except Exception as e:
            print(f"Error resizing image: {e}")
