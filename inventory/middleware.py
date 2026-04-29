from django.utils.deprecation import MiddlewareMixin
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class CheckBanMiddleware(MiddlewareMixin):
    """Middleware pour vérifier si l'utilisateur est banni à chaque requête"""
    
    def process_request(self, request):
        # Vérifier si l'utilisateur est authentifié
        if request.user.is_authenticated:
            # Vérifier si l'utilisateur a un profil
            if hasattr(request.user, 'profil'):
                profil = request.user.profil
                is_locked, lock_message = profil.is_account_locked()
                
                # Exclure certaines URLs pour éviter les boucles
                excluded_urls = ['/logout/', '/login/']
                if request.path in excluded_urls:
                    return None
                
                # Si le compte est bloqué
                if is_locked:
                    # Déconnecter l'utilisateur
                    from django.contrib.auth import logout
                    logout(request)
                    
                    # Ajouter un message d'erreur
                    messages.error(request, f"🔒 {lock_message}")
                    
                    # Rediriger vers la page de connexion
                    return redirect('login')
        
        return None