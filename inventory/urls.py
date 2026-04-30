from django.urls import path
from . import views

urlpatterns = [
    # ========== AUTHENTIFICATION ==========
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('verify-otp/', views.verify_login_otp, name='verify_login_otp'),
    path('force-password-change/', views.force_password_change, name='force_password_change'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('reset-password/<str:token>/', views.reset_password, name='reset_password'),
    
    # ========== CHANGE PASSWORD AVEC OTP (UNIFIÉ) ==========
    path('change-password/', views.change_password_request, name='change_password_request'),
    path('change-password-otp/', views.change_password_otp_verify, name='change_password_otp_verify'),
    path('request-otp-pw-change/', views.request_otp_for_password_change, name='request_otp_for_password_change'),
    
    # ========== RESET PASSWORD VIA EMAIL ==========
    path('reset-password-request/', views.reset_password_request, name='reset_password_request'),
    path('reset-password-otp/<str:token>/', views.reset_password_with_otp, name='reset_password_with_otp'),
    path('reset-password-otp-verify/', views.reset_password_otp_verify, name='reset_password_otp_verify'),
    
    # ========== HOME & DASHBOARDS ==========
    path('', views.home, name='home'),
    path('dashboard-admin/', views.dashboard_admin, name='dashboard_admin'),
    path('dashboard-user/', views.dashboard_user, name='dashboard_user'),
    path('waiting-room/', views.waiting_room, name='waiting_room'),
    
    # ========== PROFILE ==========
    path('profile/', views.user_profile, name='user_profile'),
    
    # ========== PRODUCTS ==========
    path('produits/', views.produit_list, name='produit_list'),
    path('produits/create/', views.produit_create, name='produit_create'),
    path('produits/<int:pk>/edit/', views.produit_edit, name='produit_edit'),
    path('produits/<int:pk>/delete/', views.produit_delete, name='produit_delete'),
    path('produits/<int:pk>/history/', views.produit_history, name='produit_history'),
    
    # ========== PRODUCT API ==========
    path('api/produits/', views.produit_api, name='produit_api'),
    path('api/produits/<int:pk>/', views.produit_api_detail, name='produit_api_detail'),
    path('api/notifications/<int:product_id>/read/', views.notification_mark_read, name='notification_mark_read'),
    path('api/notifications/<int:product_id>/delete/', views.notification_mark_deleted, name='notification_mark_deleted'),
    
    # ========== CLIENTS ==========
    path('clients/', views.client_list, name='client_list'),
    path('clients/create/', views.client_create, name='client_create'),
    path('clients/<int:pk>/edit/', views.client_edit, name='client_edit'),
    path('clients/<int:pk>/delete/', views.client_delete, name='client_delete'),
    path('clients/<int:pk>/history/', views.client_history, name='client_history'),
    
    # ========== FOURNISSEURS ==========
    path('fournisseurs/', views.fournisseur_list, name='fournisseur_list'),
    path('fournisseurs/create/', views.fournisseur_create, name='fournisseur_create'),
    path('fournisseurs/<int:pk>/edit/', views.fournisseur_edit, name='fournisseur_edit'),
    path('fournisseurs/<int:pk>/delete/', views.fournisseur_delete, name='fournisseur_delete'),
    path('fournisseurs/<int:pk>/history/', views.fournisseur_history, name='fournisseur_history'),
    
    # ========== USERS MANAGEMENT ==========
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/delete/', views.delete_user, name='delete_user'),
    path('users/<str:username>/history/', views.user_history, name='user_history'),
    path('users/<int:user_id>/toggle-ban/', views.toggle_user_ban, name='toggle_user_ban'),
    path('admin/create-user/', views.admin_create_user, name='admin_create_user'),
    path('admin/user/<int:pk>/edit-secure/', views.user_edit_secure, name='user_edit_secure'),
    path('user-created-info/', views.user_created_info, name='user_created_info'),
    
    # ========== ADMIN OTP ==========
    path('admin-otp-setup/', views.setup_admin_otp, name='setup_admin_otp'),
    path('admin-otp-verify/', views.admin_otp_verify, name='admin_otp_verify'),
    
    # ========== BONS ENTRÉE ==========
    path('bons-entree/', views.bon_entree_list, name='bon_entree_list'),
    path('bons-entree/create/', views.bon_entree_create, name='bon_entree_create'),
    path('bons-entree/<int:pk>/', views.bon_entree_detail, name='bon_entree_detail'),
    path('bons-entree/<int:pk>/delete/', views.bon_entree_delete, name='bon_entree_delete'),
    
    # ========== BONS SORTIE ==========
    path('bons-sortie/', views.bon_sortie_list, name='bon_sortie_list'),
    path('bons-sortie/create/', views.bon_sortie_create, name='bon_sortie_create'),
    path('bons-sortie/<int:pk>/', views.bon_sortie_detail, name='bon_sortie_detail'),
    path('bons-sortie/<int:pk>/delete/', views.bon_sortie_delete, name='bon_sortie_delete'),
    
    # ========== REPORTS ==========
    path('admin-report/', views.admin_report, name='admin_report'),
    path('data-dashboard/', views.data_dashboard, name='data_dashboard'),
    path('generate-pdf/', views.generate_pdf_report, name='generate_pdf_report'),
    
    # ========== OTHERS ==========
    path('app/', views.app_home, name='app_home'),

    # Demandes utilisateur
    path('request-email-change/', views.request_email_change, name='request_email_change'),
    path('approve-email-change/<str:token>/', views.approve_email_change, name='approve_email_change'),
    
    # Sécurité admin
    path('admin-secure-change/', views.admin_secure_change, name='admin_secure_change'),
    path('admin-confirm-change/', views.admin_confirm_change, name='admin_confirm_change'),
    path('confirm-new-email/<str:token>/', views.confirm_new_email, name='confirm_new_email'),
    path('confirm-email-with-password/<str:token>/', views.confirm_email_with_password, name='confirm_email_with_password'),
    path('mark-notification-read/<int:notification_id>/', views.mark_notification_read, name='mark_notification_read'),
    path('mark-all-notifications-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('update-all-ban-status/', views.update_all_ban_status, name='update_all_ban_status'),
    # inventory/urls.py (add inside urlpatterns)

path('api/notifications/mark-all-low-stock-read/', views.mark_all_low_stock_read, name='mark_all_low_stock_read'),
]