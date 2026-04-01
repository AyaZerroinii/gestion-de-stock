from django.db.models import F
from .models import Produit, Utilisateur, NotificationStatus

def low_stock_notifications(request):
    """Return a list of low‑stock products with per‑user read/deleted status."""
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return {
            'low_stock_count': 0,
            'low_stock_products': [],
        }

    # Get the Utilisateur instance for the current user
    utilisateur = Utilisateur.objects.filter(username=request.user.username).first()
    if not utilisateur:
        return {
            'low_stock_count': 0,
            'low_stock_products': [],
        }

    # Fetch low‑stock products (quantity <= alert threshold)
    low_stock_qs = Produit.objects.filter(qte_stock__lte=F('stock_alerte'))

    # Get set of product IDs that the user has deleted
    deleted_product_ids = set(
        NotificationStatus.objects.filter(
            utilisateur=utilisateur,
            deleted=True
        ).values_list('produit_id', flat=True)
    )

    # Exclude deleted products
    low_stock_qs = low_stock_qs.exclude(pk__in=deleted_product_ids)

    # For each remaining product, determine if it's read
    read_status = {
        ns.produit_id: ns.read
        for ns in NotificationStatus.objects.filter(
            utilisateur=utilisateur,
            produit_id__in=low_stock_qs.values_list('pk', flat=True)
        )
    }

    products_data = []
    for p in low_stock_qs.order_by('designation'):
        products_data.append({
            'code_p': p.code_p,
            'designation': p.designation,
            'qte_stock': p.qte_stock,
            'read': read_status.get(p.code_p, False),   # default to unread
        })

    return {
        'low_stock_count': len(products_data),
        'low_stock_products': products_data,
    }