from django.contrib import admin
from .models import NotificationStatus

from .models import (
    Entreprise,
    Utilisateur,
    Client,
    Fournisseur,
    Produit,
    BonEntree,
    LigneEntree,
    BonSortie,
    LigneSortie,
)


admin.site.register(NotificationStatus)
admin.site.register(Entreprise)
admin.site.register(Utilisateur)
admin.site.register(Client)
admin.site.register(Fournisseur)
admin.site.register(Produit)
admin.site.register(BonEntree)
admin.site.register(LigneEntree)
admin.site.register(BonSortie)
admin.site.register(LigneSortie)
