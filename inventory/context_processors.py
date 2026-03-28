from django.db.models import F

from .models import Produit


def low_stock_notifications(request):
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return {
            'low_stock_count': 0,
            'low_stock_products': [],
        }

    low_stock_products = Produit.objects.filter(qte_stock__lte=F('stock_alerte')).order_by('designation')
    return {
        'low_stock_count': low_stock_products.count(),
        'low_stock_products': low_stock_products,
    }
