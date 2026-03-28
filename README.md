# Gestion de Stock Django Backend

Backend Django pour application de gestion de stock basée sur le schema SQL fourni.

## Installation

1. Ouvrir terminal à `gestion-de-stock`
2. Installer dépendances :
   - `python -m pip install --break-system-packages django`
3. Créer/migrer la base :
   - `python manage.py makemigrations`
   - `python manage.py migrate`

## Démarrage

- `python manage.py runserver`
- API endpoint de test : `http://127.0.0.1:8000/api/produits/`
- UI produits : `http://127.0.0.1:8000/` (CRUD complet sur `Produit` )

## Authentification

1. Créez un superuser :
   - `python manage.py createsuperuser`
2. Allez à `http://127.0.0.1:8000/accounts/login/` pour vous connecter.
3. Après connexion :
   - ouvrir `http://127.0.0.1:8000/` ou `http://127.0.0.1:8000/app/` pour l'application web moderne (SPA)
   - ouvrir `http://127.0.0.1:8000/bon-entrees/` pour voir toute  العمليات الدخول
   - ouvrir `http://127.0.0.1:8000/bon-sorties/` لتنظيم عمليات الخروج
   - ouvrir `http://127.0.0.1:8000/users/` لإدارة الموظفين
   - ouvrir `http://127.0.0.1:8000/admin/` pour panneau d'administration Django

## Utilisation

1. Allez sur `http://127.0.0.1:8000/`.
2. Ajoutez, modifiez, supprimez des produits.
3. Vérifiez JSON in `http://127.0.0.1:8000/api/produits/`.

## Modèles (tables)
- Entreprise
- Utilisateur
- Client
- Fournisseur
- Produit
- BonEntree (entrée de stock)
- LigneEntree
- BonSortie (sortie de stock)
- LigneSortie
