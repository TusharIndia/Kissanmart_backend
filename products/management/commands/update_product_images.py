"""
Django management command to update product images to HD quality with category-based search.
Usage: python manage.py update_product_images [--force] [--limit N]
"""

from django.core.management.base import BaseCommand
from django.db.models import Q
from products.models import Product
from products.services import pexels_service
import time


class Command(BaseCommand):
    help = 'Update product images to HD quality with improved category-based search'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update even for products that already have images',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit the number of products to process',
        )
        parser.add_argument(
            '--category',
            type=str,
            default=None,
            help='Only process products from a specific category',
        )
        parser.add_argument(
            '--missing-only',
            action='store_true',
            help='Only process products that don\'t have images',
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Starting HD product image update process...')
        )

        # Build query
        queryset = Product.objects.filter(is_published=True)
        
        if options['missing_only']:
            queryset = queryset.filter(
                Q(pexels_image_url__isnull=True) | Q(pexels_image_url='')
            )
        elif not options['force']:
            # By default, only update products without images
            queryset = queryset.filter(
                Q(pexels_image_url__isnull=True) | Q(pexels_image_url='')
            )

        if options['category']:
            queryset = queryset.filter(category__icontains=options['category'])

        if options['limit']:
            queryset = queryset[:options['limit']]

        total_products = queryset.count()
        
        if total_products == 0:
            self.stdout.write(
                self.style.WARNING('No products found matching the criteria.')
            )
            return

        self.stdout.write(
            f'Found {total_products} products to process'
        )

        success_count = 0
        error_count = 0
        skipped_count = 0

        for i, product in enumerate(queryset, 1):
            self.stdout.write(
                f'\nProcessing {i}/{total_products}: {product.title} '
                f'(Category: {product.category or "None"})'
            )

            try:
                if options['force'] and product.pexels_image_url:
                    # Force refresh existing image
                    image_url = pexels_service.refresh_product_image(product, force_new_search=True)
                else:
                    # Get or fetch new image
                    image_url = pexels_service.get_or_fetch_product_image(product)

                if image_url:
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ Updated: {image_url}')
                    )
                    success_count += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(f'  ⚠ No suitable image found')
                    )
                    skipped_count += 1

                # Add small delay to respect API rate limits
                time.sleep(0.5)

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Error: {str(e)}')
                )
                error_count += 1

        # Summary
        self.stdout.write('\n' + '='*50)
        self.stdout.write(
            self.style.SUCCESS(
                f'Update completed!\n'
                f'Processed: {total_products} products\n'
                f'Success: {success_count}\n'
                f'Skipped: {skipped_count}\n'
                f'Errors: {error_count}'
            )
        )
        
        if success_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n🎉 Successfully updated {success_count} products with HD images!'
                )
            )