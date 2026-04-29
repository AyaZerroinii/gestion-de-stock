from .models import Produit, Utilisateur, Notification, NotificationStatus
from django.db.models import F, Q
from django.utils import timezone

def low_stock_notifications(request):
    if request.user.is_authenticated and hasattr(request.user, 'profil'):
        user_profil = request.user.profil
        low_stock_products = Produit.objects.filter(qte_stock__lte=F('stock_alerte'))
        
        notifications = []
        unread_count = 0
        
        for produit in low_stock_products:
            try:
                status = NotificationStatus.objects.get(utilisateur=user_profil, produit=produit)
                is_read = status.read
                is_deleted = status.deleted
            except NotificationStatus.DoesNotExist:
                is_read = False
                is_deleted = False
            
            if not is_deleted:
                notifications.append({
                    'id': produit.code_p,
                    'type': 'stock',
                    'title': 'Stock faible',
                    'message': f"'{produit.designation}' : {produit.qte_stock} unités",
                    'link': f'/produits/',
                    'is_read': is_read,
                    'created_at': timezone.now(),
                })
                if not is_read:
                    unread_count += 1
        
        return {
            'low_stock_notifications': notifications[:10],
            'low_stock_unread_count': unread_count,
        }
    return {'low_stock_notifications': [], 'low_stock_unread_count': 0}

def system_notifications(request):
    """Context processor for system notifications (email changes, etc.)"""
    if request.user.is_authenticated and hasattr(request.user, 'profil'):
        notifs = Notification.objects.filter(recipient=request.user.profil).order_by('-created_at')[:15]
        unread_count = Notification.objects.filter(recipient=request.user.profil, is_read=False).count()
        
        notifications = []
        for notif in notifs:
            notifications.append({
                'id': notif.id,
                'type': 'system',
                'title': notif.title,
                'message': notif.message,
                'link': notif.link,
                'is_read': notif.is_read,
                'created_at': notif.created_at,
            })
        
        return {
            'system_notifications': notifications,
            'system_unread_count': unread_count,
        }
    return {
        'system_notifications': [],
        'system_unread_count': 0,
    }


def combined_notifications(request):
    """Combine both low stock and system notifications"""
    low_stock = low_stock_notifications(request)
    system = system_notifications(request)
    
    # دمج الإشعارات
    all_notifications = []
    
    # إضافة إشعارات المخزون المنخفض
    all_notifications.extend(low_stock.get('low_stock_notifications', []))
    
    # إضافة الإشعارات النظامية
    all_notifications.extend(system.get('system_notifications', []))
    
    # ✅ ترتيب حسب التاريخ (الأحدث أولاً) - الآن الكل من نفس النوع (datetime)
    all_notifications.sort(key=lambda x: x['created_at'], reverse=True)
    
    # حساب عدد غير المقروء
    unread_count = low_stock.get('low_stock_unread_count', 0) + system.get('system_unread_count', 0)
    
    return {
        'notifications': all_notifications[:20],
        'unread_notifications_count': unread_count,
    }