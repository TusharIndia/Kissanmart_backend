from rest_framework.permissions import BasePermission


class IsSmartBuyer(BasePermission):
    """
    Custom permission to only allow smart_buyer users to access cart functionality.
    """
    
    def has_permission(self, request, view):
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Check if user is a smart_buyer
        return request.user.user_type == 'smart_buyer'
    
    message = "Cart access is only available for Smart Buyer users."