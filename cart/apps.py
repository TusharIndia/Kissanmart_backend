from django.apps import AppConfig


class CartConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cart'
    verbose_name = 'Shopping Cart'
    
    def ready(self):
        """Import signals when app is ready"""
        try:
            import cart.signals  # noqa F401
        except ImportError:
            pass
