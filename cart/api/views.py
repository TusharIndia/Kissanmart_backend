from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from cart.models import Cart, CartItem
from products.models import Product
from cart.permissions import IsSmartBuyer
from cart.api.serializers import (
    CartSerializer, CartItemSerializer, AddToCartSerializer
)


class CartViewSet(viewsets.GenericViewSet):
    """
    ViewSet for cart management (Smart Buyer users only)
    Provides endpoints for:
    - Get all cart items
    - Add item to cart
    - Remove specific item from cart
    - Remove all items from cart
    """
    permission_classes = [IsSmartBuyer]
    serializer_class = CartSerializer

    def get_object(self):
        """Get or create cart for current user"""
        cart, created = Cart.objects.get_or_create(user=self.request.user)
        return cart

    def list(self, request):
        """Get all cart items for current user"""
        cart = self.get_object()
        serializer = self.get_serializer(cart)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def add_item(self, request):
        """Add item to cart"""
        serializer = AddToCartSerializer(
            data=request.data, 
            context={'request': request}
        )
        
        if serializer.is_valid():
            try:
                cart_item = serializer.save()
                cart_item_serializer = CartItemSerializer(cart_item)
                return Response({
                    'message': 'Item added to cart successfully',
                    'item': cart_item_serializer.data
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({
                    'error': f'Failed to add item to cart: {str(e)}'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['delete'])
    def remove_item(self, request):
        """Remove specific item from cart"""
        item_id = request.query_params.get('item_id')
        if not item_id:
            return Response({
                'error': 'item_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        cart = self.get_object()
        try:
            cart_item = cart.items.get(id=item_id)
            product_title = cart_item.product.title
            cart_item.delete()
            return Response({
                'message': f'{product_title} removed from cart successfully'
            })
        except CartItem.DoesNotExist:
            return Response({
                'error': 'Cart item not found'
            }, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['delete'])
    def clear_cart(self, request):
        """Remove all items from cart"""
        cart = self.get_object()
        items_count = cart.items.count()
        cart.clear()
        return Response({
            'message': f'Cart cleared successfully. {items_count} items removed.'
        })