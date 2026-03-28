from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard-admin/', views.dashboard_admin, name='dashboard_admin'),
    path('dashboard-user/', views.dashboard_user, name='dashboard_user'),
    path('app/', views.app_home, name='app_home'),
    path('produits/', views.produit_list, name='produit_list'),
    path('produits/new/', views.produit_create, name='produit_create'),
    path('produits/<int:pk>/edit/', views.produit_edit, name='produit_edit'),
    path('produits/<int:pk>/delete/', views.produit_delete, name='produit_delete'),
    path('users/', views.user_management, name='user_management'),
    path('users/<int:pk>/delete/', views.delete_user, name='delete_user'),
    path('bon-entrees/', views.bon_entree_list, name='bon_entree_list'),
    path('bon-entrees/new/', views.bon_entree_create, name='bon_entree_create'),
    path('bon-entrees/<int:pk>/', views.bon_entree_detail, name='bon_entree_detail'),
    path('bon-sorties/', views.bon_sortie_list, name='bon_sortie_list'),
    path('bon-sorties/new/', views.bon_sortie_create, name='bon_sortie_create'),
    path('bon-sorties/<int:pk>/', views.bon_sortie_detail, name='bon_sortie_detail'),
    path('clients/', views.client_list, name='client_list'),
    path('clients/new/', views.client_create, name='client_create'),
    path('clients/<int:pk>/edit/', views.client_edit, name='client_edit'),
    path('clients/<int:pk>/delete/', views.client_delete, name='client_delete'),
    path('api/produits/', views.produit_api, name='produit_api'),
    path('api/produits/<int:pk>/', views.produit_api_detail, name='produit_api_detail'),
]
