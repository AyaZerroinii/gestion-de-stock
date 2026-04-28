from .models import Produit, Utilisateur, NotificationStatus
from django.db.models import F

def low_stock_notifications(request):
    """
    Context processor to add low stock notifications to all templates
    """
    if not request.user.is_authenticated:
        return {}
    
    try:
        # الطريقة الصحيحة للوصول إلى profil المستخدم
        if hasattr(request.user, 'profil'):
            utilisateur = request.user.profil
        else:
            # إذا ما عندوش profil، حاول تجيبه أو ارجع None
            utilisateur = None
        
        # جلب المنتجات ذات المخزون المنخفض
        low_stock_products = Produit.objects.filter(
            qte_stock__lte=F('stock_alerte')
        ).order_by('designation')[:10]
        
        # جلب إشعارات غير مقروءة للمستخدم
        unread_count = 0
        if utilisateur:
            unread_count = NotificationStatus.objects.filter(
                utilisateur=utilisateur,
                read=False,
                deleted=False,
                produit__in=low_stock_products
            ).count()
        
        return {
            'low_stock_products': low_stock_products,
            'low_stock_count': low_stock_products.count(),
            'unread_notifications_count': unread_count,
        }
    except Exception as e:
        # في حالة أي خطأ، نرجع قاموس فارغ
        return {}