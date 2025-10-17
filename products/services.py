"""
Services for handling product-related operations including image fetching from Pexels API.
"""
import requests
import logging
from django.conf import settings
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

class PexelsImageService:
    """Service class for fetching high-quality product images from Pexels API."""
    
    BASE_URL = "https://api.pexels.com/v1/search"
    
    # Category mapping for better search results
    CATEGORY_KEYWORDS = {
        'fruit': ['fruit', 'fresh fruit', 'organic fruit'],
        'vegetable': ['vegetable', 'fresh vegetable', 'organic vegetable'],
        'grain': ['grain', 'cereal', 'agricultural grain'],
        'spice': ['spice', 'herbs', 'seasoning'],
        'dairy': ['dairy', 'milk product', 'farm dairy'],
        'meat': ['meat', 'fresh meat', 'protein'],
        'seafood': ['fish', 'seafood', 'fresh fish'],
        'pulse': ['pulses', 'legumes', 'lentils'],
        'oil': ['cooking oil', 'edible oil', 'organic oil'],
        'nuts': ['nuts', 'dry fruits', 'healthy nuts'],
        'seeds': ['seeds', 'agricultural seeds', 'organic seeds'],
        'herbs': ['fresh herbs', 'medicinal herbs', 'organic herbs'],
        'flower': ['flowers', 'fresh flowers', 'garden flowers'],
        'tea': ['tea leaves', 'organic tea', 'fresh tea'],
        'coffee': ['coffee beans', 'organic coffee', 'fresh coffee'],
    }
    
    def __init__(self):
        self.api_key = getattr(settings, 'PEXELS_API_KEY', None)
        if not self.api_key:
            logger.warning("PEXELS_API_KEY not found in settings. Image fetching will be disabled.")
    
    def is_configured(self):
        """Check if the service is properly configured."""
        return bool(self.api_key)
    
    def _get_category_keywords(self, category: str) -> List[str]:
        """
        Get relevant keywords for a product category.
        
        Args:
            category (str): Product category
            
        Returns:
            List[str]: List of relevant keywords for the category
        """
        if not category:
            return []
            
        category_lower = category.lower()
        
        # Direct match
        if category_lower in self.CATEGORY_KEYWORDS:
            return self.CATEGORY_KEYWORDS[category_lower]
        
        # Partial match
        for cat_key, keywords in self.CATEGORY_KEYWORDS.items():
            if cat_key in category_lower or category_lower in cat_key:
                return keywords
        
        return []
    
    def _generate_search_queries(self, product_title: str, category: str = None) -> List[str]:
        """
        Generate multiple search queries for better image results.
        
        Args:
            product_title (str): Product title/name
            category (str): Product category
            
        Returns:
            List[str]: List of search queries ordered by preference
        """
        queries = []
        title_clean = product_title.strip().lower()
        
        # Get category keywords
        category_keywords = self._get_category_keywords(category) if category else []
        
        # Priority 1: Product + specific category keywords
        if category_keywords:
            for keyword in category_keywords[:2]:  # Use top 2 category keywords
                queries.append(f"{title_clean} {keyword}")
        
        # Priority 2: Product + generic food/fresh keywords
        queries.extend([
            f"{title_clean} fresh",
            f"fresh {title_clean}",
            f"{title_clean} organic",
            f"organic {title_clean}"
        ])
        
        # Priority 3: Just the product name
        queries.append(title_clean)
        
        # Priority 4: Product + food (as fallback)
        queries.append(f"{title_clean} food")
        
        return queries
    
    def fetch_product_image_url(self, product_title: str, category: str = None) -> Optional[str]:
        """
        Fetch a high-quality product image URL from Pexels API.
        
        Args:
            product_title (str): The title/name of the product to search for
            category (str): The category of the product for better search results
            
        Returns:
            Optional[str]: HD Image URL if found, None otherwise
        """
        if not self.api_key:
            logger.error("Pexels API key not configured")
            return None
            
        if not product_title or not product_title.strip():
            return None
            
        # Generate search queries
        search_queries = self._generate_search_queries(product_title, category)
        
        headers = {
            'Authorization': self.api_key
        }
        
        # Try each search query until we find a good image
        for query in search_queries:
            try:
                params = {
                    'query': query,
                    'per_page': 3,  # Get more options to choose from
                    'orientation': 'landscape',  # Better for product display
                    'size': 'large',  # Request larger images
                    'locale': 'en-US'  # Ensure consistent results
                }
                
                response = requests.get(
                    self.BASE_URL,
                    headers=headers,
                    params=params,
                    timeout=15
                )
                
                if not response.ok:
                    logger.debug(f"Pexels API error for query '{query}': {response.status_code}")
                    continue
                    
                data = response.json()
                
                if data.get('photos') and len(data['photos']) > 0:
                    # Select the best image (first one is usually most relevant)
                    photo = data['photos'][0]
                    
                    # Prefer HD quality images
                    image_sizes = photo.get('src', {})
                    
                    # Priority order for image quality (HD first)
                    # large2x = HD quality with 2x pixel density, original = full resolution
                    size_priority = ['large2x', 'original', 'large', 'medium', 'small']
                    
                    image_url = None
                    for size in size_priority:
                        if size in image_sizes:
                            image_url = image_sizes[size]
                            break
                    
                    if image_url:
                        return image_url
                        
            except requests.exceptions.RequestException as e:
                logger.debug(f"Network error for query '{query}': {str(e)}")
                continue
            except Exception as e:
                logger.debug(f"Error processing query '{query}': {str(e)}")
                continue
        
        return None

    def get_or_fetch_product_image(self, product):
        """
        Get existing product image URL or fetch new HD image if not exists.
        
        Args:
            product: Product model instance
            
        Returns:
            Optional[str]: HD Image URL if available
        """
        # Refresh product from database to ensure we have the latest pexels_image_url
        product.refresh_from_db(fields=['pexels_image_url'])
        
        # If product already has a Pexels image URL, return it
        if product.pexels_image_url:
            return product.pexels_image_url
            
        # Check if another product with the same title and category already has an image
        from .models import Product
        existing_product = Product.objects.filter(
            title__iexact=product.title,
            category=product.category,  # Direct comparison since both are Category instances
            pexels_image_url__isnull=False
        ).exclude(id=product.id).first()
        
        if existing_product:
            # Use the same image URL for products with the same title and category
            product.pexels_image_url = existing_product.pexels_image_url
            product.save(update_fields=['pexels_image_url'])
            return product.pexels_image_url
            
        # Prevent duplicate requests for the same product
        from django.core.cache import cache
        cache_key = f"fetching_image_{product.id}"
        
        if cache.get(cache_key):
            return None
            
        # Set cache flag to prevent concurrent requests
        cache.set(cache_key, True, 30)  # 30 seconds timeout
        
        try:
            # Fetch new HD image from Pexels API with category context
            category_name = product.category.name if product.category else None
            image_url = self.fetch_product_image_url(product.title, category_name)
            if image_url:
                product.pexels_image_url = image_url
                product.save(update_fields=['pexels_image_url'])
        except Exception as e:
            logger.error(f"Error fetching image for product {product.title}: {str(e)}")
            image_url = None
        finally:
            # Clear cache flag
            cache.delete(cache_key)
            
        return image_url
    
    def refresh_product_image(self, product, force_new_search: bool = False):
        """
        Refresh/update the product image with a new search.
        Useful for getting better quality images or when current image is not suitable.
        
        Args:
            product: Product model instance
            force_new_search (bool): If True, fetch new image even if one exists
            
        Returns:
            Optional[str]: New HD Image URL if found
        """
        if not force_new_search and product.pexels_image_url:
            return product.pexels_image_url
            
        # Clear existing image URL to force new fetch
        old_url = product.pexels_image_url
        product.pexels_image_url = None
        
        # Fetch new HD image
        category_name = product.category.name if product.category else None
        image_url = self.fetch_product_image_url(product.title, category_name)
        if image_url:
            product.pexels_image_url = image_url
            product.save(update_fields=['pexels_image_url'])
        else:
            # Restore old URL if new fetch failed
            product.pexels_image_url = old_url
            product.save(update_fields=['pexels_image_url'])
            
        return product.pexels_image_url


# Create a singleton instance
pexels_service = PexelsImageService()