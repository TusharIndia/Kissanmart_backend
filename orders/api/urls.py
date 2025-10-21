from django.urls import path, include
from . import views, admin_views, razorpay_views, seller_views, shiprocket_views, cancellation_views

# Core order API URLs
urlpatterns = [
    # Core Order APIs
    path('create/', views.CreateOrderView.as_view(), name='create_order'),
    path('my-orders/', views.UserOrdersView.as_view(), name='user_orders'),
    path('<uuid:order_uuid>/', views.OrderDetailView.as_view(), name='order_detail'),
    path('<uuid:order_uuid>/status/', views.UpdateOrderStatusView.as_view(), name='update_order_status'),
    path('<uuid:order_uuid>/cancel/', views.CancelOrderView.as_view(), name='cancel_order'),
    path('<uuid:order_uuid>/reorder/', views.ReorderView.as_view(), name='reorder'),
    
    # Order Tracking APIs
    path('<uuid:order_uuid>/tracking/', views.OrderTrackingView.as_view(), name='order_tracking'),
    path('<uuid:order_uuid>/live-tracking/', views.LiveTrackingView.as_view(), name='live_tracking'),
    
    # Payment APIs
    path('<uuid:order_uuid>/payment/', views.ProcessPaymentView.as_view(), name='process_payment'),
    path('<uuid:order_uuid>/payment-status/', views.PaymentStatusView.as_view(), name='payment_status'),
    
    # Razorpay Payment APIs
    path('<uuid:order_uuid>/razorpay/create/', razorpay_views.CreateRazorpayOrderView.as_view(), name='create_razorpay_order'),
    path('<uuid:order_uuid>/razorpay/verify/', razorpay_views.VerifyRazorpayPaymentView.as_view(), name='verify_razorpay_payment'),
    path('<uuid:order_uuid>/razorpay/status/', razorpay_views.RazorpayPaymentStatusView.as_view(), name='razorpay_payment_status'),
    path('razorpay/webhook/', razorpay_views.handle_razorpay_webhook, name='razorpay_webhook'),
    path('razorpay/debug/', razorpay_views.debug_razorpay_request, name='debug_razorpay_request'),
    
    # Shipping Update API
    path('<uuid:order_uuid>/shipping/update/', razorpay_views.UpdateOrderShippingView.as_view(), name='update_order_shipping'),
    
    # Analytics APIs
    path('statistics/', views.OrderStatisticsView.as_view(), name='order_statistics'),
    
    # Shiprocket APIs
    path('shiprocket/serviceability/', shiprocket_views.CourierServiceabilityView.as_view(), name='shiprocket_serviceability'),
    path('shiprocket/shipping-calculator/', shiprocket_views.ShippingCalculatorView.as_view(), name='shipping_calculator'),
    path('shiprocket/pickup-locations/', shiprocket_views.pickup_locations, name='pickup_locations'),
    path('<uuid:order_uuid>/shiprocket/create/', shiprocket_views.CreateShiprocketOrderView.as_view(), name='create_shiprocket_order'),
    path('<uuid:order_uuid>/shiprocket/track/', shiprocket_views.TrackShiprocketOrderView.as_view(), name='track_shiprocket_order'),
    path('<uuid:order_uuid>/shiprocket/calculate/', shiprocket_views.OrderShippingCalculatorView.as_view(), name='order_shipping_calculator'),
    
    # Seller Order APIs
    path('seller/orders/', seller_views.SellerOrdersView.as_view(), name='seller_orders'),
    path('seller/orders/<uuid:order_uuid>/', seller_views.SellerOrderDetailView.as_view(), name='seller_order_detail'),
    path('seller/orders/<uuid:order_uuid>/items/<uuid:item_id>/', seller_views.SellerOrderItemUpdateView.as_view(), name='seller_order_item_update'),
    path('seller/items/bulk-update/', seller_views.SellerBulkOrderUpdateView.as_view(), name='seller_bulk_update'),
    path('seller/statistics/', seller_views.SellerOrderStatisticsView.as_view(), name='seller_statistics'),
    path('seller/inventory/', seller_views.SellerProductInventoryView.as_view(), name='seller_inventory'),
    path('seller/dashboard/', seller_views.seller_dashboard_summary, name='seller_dashboard'),
    
    # Admin Order APIs
    path('admin/orders/', admin_views.AdminOrderListView.as_view(), name='admin_order_list'),
    path('admin/orders/<uuid:order_uuid>/', admin_views.AdminOrderDetailView.as_view(), name='admin_order_detail'),
    path('admin/analytics/', admin_views.AdminOrderAnalyticsView.as_view(), name='admin_analytics'),
    path('admin/dashboard/', admin_views.AdminDashboardStatsView.as_view(), name='admin_dashboard'),
    # Payment mode charges management
    path('admin/payment-charges/', admin_views.AdminPaymentModeChargeListCreate.as_view(), name='admin_payment_charges'),
    path('admin/payment-charges/<int:pk>/', admin_views.AdminPaymentModeChargeDetail.as_view(), name='admin_payment_charge_detail'),
    # Public payment charges for frontend display
    path('payment-charges/', admin_views.PublicPaymentModeChargesView.as_view(), name='public_payment_charges'),
    
    # Cancellation & Refund APIs
    path('<uuid:order_uuid>/cancellation/eligibility/', cancellation_views.CheckOrderCancellationEligibilityView.as_view(), name='cancellation_eligibility'),
    path('<uuid:order_uuid>/cancellation/request/', cancellation_views.CreateCancellationRequestView.as_view(), name='create_cancellation_request'),
    path('<uuid:order_uuid>/cancellation/', cancellation_views.CancellationRequestDetailView.as_view(), name='cancellation_detail'),

    # Admin cancellation management
    path('admin/cancellations/', cancellation_views.AdminCancellationRequestListView.as_view(), name='admin_cancellation_list'),
    path('admin/cancellations/<uuid:cancellation_request_id>/process/', cancellation_views.AdminProcessRefundView.as_view(), name='admin_process_refund'),
    path('admin/cancellations/<uuid:cancellation_request_id>/reject/', cancellation_views.AdminRejectCancellationView.as_view(), name='admin_reject_cancellation'),
    path('admin/cancellations/stats/', cancellation_views.admin_cancellation_stats, name='admin_cancellation_stats'),
]