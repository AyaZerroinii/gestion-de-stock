import json
import secrets
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseRedirect, HttpResponseForbidden
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.db import IntegrityError, models
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.db.models import Sum, Q, F, Count
from django.utils.dateparse import parse_date
from django.core.mail import send_mail
from django.conf import settings

from .forms import AdminUserCreationForm, ProduitForm, ForcePasswordChangeForm, ForgotPasswordForm, ResetPasswordForm, AdminOTPForm
from .models import (
    Entreprise, Produit, Utilisateur, Fournisseur, 
    Client, BonEntree, LigneEntree, BonSortie, LigneSortie, NotificationStatus
)

import pyotp
from .utils import notify_admin_password_change
from .utils import send_email_to_user, notify_admin_forgot_password
LOW_STOCK = 50


# ========== DECORATORS ==========
def staff_or_superuser_required(view_func):
    actual_decorator = user_passes_test(
        lambda u: u.is_authenticated and (u.is_staff or u.is_superuser),
        login_url='waiting_room',
        redirect_field_name=None
    )
    return actual_decorator(view_func)


# ========== NOTIFICATIONS API ==========
@login_required
@staff_or_superuser_required
@csrf_exempt
@require_POST
def notification_mark_read(request, product_id):
    """Mark a low‑stock notification as read for the current user."""
    try:
        produit = Produit.objects.get(pk=product_id)
    except Produit.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)

    utilisateur = request.user.profil  # Utilisation directe via OneToOne

    status_obj, created = NotificationStatus.objects.get_or_create(
        utilisateur=utilisateur,
        produit=produit,
        defaults={'read': True}
    )
    if not created:
        status_obj.read = True
        status_obj.save()

    return JsonResponse({'status': 'ok'})


@login_required
@staff_or_superuser_required
@csrf_exempt
@require_POST
def notification_mark_deleted(request, product_id):
    """Mark a low‑stock notification as deleted for the current user."""
    try:
        produit = Produit.objects.get(pk=product_id)
    except Produit.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)

    utilisateur = request.user.profil

    status_obj, created = NotificationStatus.objects.get_or_create(
        utilisateur=utilisateur,
        produit=produit,
        defaults={'deleted': True}
    )
    if not created:
        status_obj.deleted = True
        status_obj.save()

    return JsonResponse({'status': 'ok'})


# ========== AUTHENTICATION & HOME ==========
def custom_login(request):
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Vérifier si l'utilisateur existe dans Utilisateur via OneToOne
        try:
            user_obj = User.objects.get(username=username)
            if hasattr(user_obj, 'profil'):
                utilisateur_obj = user_obj.profil
                
                # Vérifier si le compte est bloqué
                is_locked, lock_message = utilisateur_obj.is_account_locked()
                if is_locked:
                    messages.error(request, f"🔒 {lock_message}")
                    return redirect('login')
        except User.DoesNotExist:
            pass
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Réinitialiser les tentatives échouées
            if hasattr(user, 'profil'):
                user.profil.reset_failed_attempts()
            
            # Stocker l'ID utilisateur en session pour l'OTP
            request.session['pre_otp_user_id'] = user.id
            
            # Vérifier si l'utilisateur est admin et a OTP activé
            if user.is_superuser and hasattr(user, 'profil') and user.profil.otp_enabled:
                return redirect('admin_otp_verify')
            
            # Connexion directe
            login(request, user)
            
            # Vérifier si l'utilisateur doit changer son mot de passe
            if hasattr(user, 'profil') and user.profil.must_change_password:
                return redirect('force_password_change')
            
            return redirect('home')
        else:
            # Incrémenter les tentatives échouées
            try:
                user_obj = User.objects.get(username=username)
                if hasattr(user_obj, 'profil'):
                    user_obj.profil.increment_failed_attempts()
            except User.DoesNotExist:
                pass
            messages.error(request, "❌ Nom d'utilisateur ou mot de passe incorrect.")
    
    return render(request, 'inventory/login.html')


@login_required(login_url='login')
def home(request):
    if request.user.is_superuser:
        return HttpResponseRedirect(reverse('dashboard_admin'))
    if not request.user.is_staff:
        return HttpResponseRedirect(reverse('waiting_room'))
    return HttpResponseRedirect(reverse('dashboard_user'))


@login_required(login_url='login')
def waiting_room(request):
    return render(request, 'inventory/waiting_room.html')


# ========== FORCER LE CHANGEMENT DE MOT DE PASSE ==========
@login_required
def force_password_change(request):
    # Vérifier si l'utilisateur doit changer son mot de passe
    if not hasattr(request.user, 'profil') or not request.user.profil.must_change_password:
        return redirect('home')
    
    if request.method == 'POST':
        form = ForcePasswordChangeForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            request.user.set_password(new_password)
            request.user.save()
            
            profil = request.user.profil
            profil.must_change_password = False
            profil.password_changed_at = timezone.now()
            profil.save()
            
            # Re-authentifier l'utilisateur
            update_session_auth_hash(request, request.user)
            
            messages.success(request, "✅ Votre mot de passe a été changé avec succès.")
            return redirect('home')
    else:
        form = ForcePasswordChangeForm()
    
    return render(request, 'inventory/force_password_change.html', {'form': form})


# ========== FORGOT PASSWORD ==========
def forgot_password(request):
    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = User.objects.get(email=email)
                if hasattr(user, 'profil'):
                    profil = user.profil
                    
                    import secrets
                    token = secrets.token_urlsafe(32)
                    profil.reset_password_token = token
                    profil.reset_token_expires = timezone.now() + timezone.timedelta(hours=24)
                    profil.save()
                    
                    reset_link = request.build_absolute_uri(reverse('reset_password', args=[token]))
                    
                    # ========== 🔔 إشعار للأدمن ==========
                    from .utils import notify_admin_forgot_password
                    notify_admin_forgot_password(user)
                    # =====================================
                    
                    messages.success(request, "📧 Un email de réinitialisation a été envoyé.")
            except User.DoesNotExist:
                messages.success(request, "📧 Si cet email existe, un lien de réinitialisation a été envoyé.")
            return redirect('login')
    else:
        form = ForgotPasswordForm()
    return render(request, 'inventory/forgot_password.html', {'form': form})


# ========== RESET PASSWORD ==========
def reset_password(request, token):
    try:
        profil = Utilisateur.objects.get(reset_password_token=token, reset_token_expires__gt=timezone.now())
        user = profil.user
    except Utilisateur.DoesNotExist:
        messages.error(request, "❌ Lien invalide ou expiré.")
        return redirect('login')
    
    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            user.set_password(new_password)
            user.save()
            
            profil.reset_password_token = None
            profil.reset_token_expires = None
            profil.must_change_password = False
            profil.save()
            
            messages.success(request, "✅ Votre mot de passe a été réinitialisé. Vous pouvez maintenant vous connecter.")
            return redirect('login')
    else:
        form = ResetPasswordForm()
    
    return render(request, 'inventory/reset_password.html', {'form': form, 'token': token})


# ========== ADMIN OTP ==========
@login_required
def admin_otp_verify(request):
    # Vérifier que l'utilisateur vient de la page login
    if not request.session.get('pre_otp_user_id'):
        return redirect('login')
    
    user_id = request.session.get('pre_otp_user_id')
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        form = AdminOTPForm(request.POST)
        if form.is_valid():
            otp_code = form.cleaned_data['otp_code']
            if hasattr(user, 'profil') and user.profil.otp_enabled:
                totp = pyotp.TOTP(user.profil.otp_secret)
                if totp.verify(otp_code):
                    login(request, user)
                    del request.session['pre_otp_user_id']
                    return redirect('home')
                else:
                    messages.error(request, "❌ Code OTP invalide.")
    else:
        form = AdminOTPForm()
    
    return render(request, 'inventory/admin_otp_verify.html', {'form': form, 'user': user})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def setup_admin_otp(request):
    profil, created = Utilisateur.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        if 'enable' in request.POST:
            # Générer secret OTP
            secret = pyotp.random_base32()
            profil.otp_secret = secret
            profil.otp_enabled = True
            profil.save()
            
            # Générer QR code URI
            totp = pyotp.TOTP(secret)
            otp_uri = totp.provisioning_uri(name=request.user.email, issuer_name="Gestion Stock")
            
            messages.success(request, "✅ OTP activé. Scannez le code QR avec Google Authenticator.")
            return render(request, 'inventory/admin_otp_setup.html', {'otp_uri': otp_uri, 'secret': secret})
        
        elif 'disable' in request.POST:
            profil.otp_enabled = False
            profil.otp_secret = None
            profil.save()
            messages.success(request, "✅ OTP désactivé.")
            return redirect('home')
    
    return render(request, 'inventory/admin_otp_setup.html', {'otp_enabled': profil.otp_enabled})


# ========== DASHBOARDS ==========
@login_required(login_url='login')
def dashboard_admin(request):
    if not request.user.is_superuser:
        return redirect('dashboard_user')
    
    today = timezone.now()
    first_day = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    entrees_mois = BonEntree.objects.filter(date_e__gte=first_day).count()
    sorties_mois = BonSortie.objects.filter(date_s__gte=first_day).count()
    total_produits = Produit.objects.count()
    low_stock = Produit.objects.filter(qte_stock__lte=F('stock_alerte')).count()
    
    # Derniers mouvements
    dernieres_entrees = BonEntree.objects.order_by('-date_e')[:5]
    dernieres_sorties = BonSortie.objects.order_by('-date_s')[:5]
    mouvements = []
    for e in dernieres_entrees:
        total_qte = e.lignes.aggregate(s=Sum('qte_e'))['s'] or 0
        mouvements.append({
            'designation': f"Entrée #{e.num_e} - {e.fournisseur.designation}",
            'qte': total_qte,
            'date': e.date_e,
            'type_icon': 'arrow-down-circle',
            'color': 'success'
        })
    for s in dernieres_sorties:
        total_qte = s.lignes.aggregate(s=Sum('qte_s'))['s'] or 0
        mouvements.append({
            'designation': f"Sortie #{s.num_s} - {s.client.designation}",
            'qte': total_qte,
            'date': s.date_s,
            'type_icon': 'arrow-up-circle',
            'color': 'danger'
        })
    mouvements.sort(key=lambda x: x['date'], reverse=True)
    
    produits_critiques = Produit.objects.filter(qte_stock__lte=F('stock_alerte'))[:5]
    
    context = {
        'total_produits': total_produits,
        'low_stock': low_stock,
        'entrees_mois': entrees_mois,
        'sorties_mois': sorties_mois,
        'derniers_mouvements': mouvements[:8],
        'produits_critiques': produits_critiques,
    }
    return render(request, 'inventory/dashboard_admin.html', context)


@staff_or_superuser_required
@login_required(login_url='login')
def dashboard_user(request):
    if request.user.is_superuser:
        return redirect('dashboard_admin')

    if not request.user.is_staff:
        return redirect('waiting_room')
    
    utilisateur_obj = request.user.profil  # Utilisation directe
    
    recent_entrees = BonEntree.objects.filter(utilisateur=utilisateur_obj).order_by('-date_e')[:5]
    recent_sorties = BonSortie.objects.filter(utilisateur=utilisateur_obj).order_by('-date_s')[:5]
    
    all_products = Produit.objects.all().order_by('designation')
    low_stock_count = Produit.objects.filter(qte_stock__lte=F('stock_alerte')).count()
    
    return render(request, 'inventory/dashboard_user.html', {
        'recent_entrees': recent_entrees,
        'recent_sorties': recent_sorties,
        'all_products': all_products,
        'total_produits': all_products.count(),
        'low_stock_count': low_stock_count,
    })


# ========== USER PROFILE ==========
from django.core.mail import send_mail
from django.conf import settings
@login_required
def user_profile(request):
    if request.method == 'POST':
        user = request.user
        user.username = request.POST.get('username')
        user.email = request.POST.get('email')
        user.first_name = request.POST.get('first_name', '')
        user.last_name = request.POST.get('last_name', '')
        
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if new_password:
            if new_password == confirm_password:
                if len(new_password) >= 8:
                    user.set_password(new_password)
                    update_session_auth_hash(request, user)
                    messages.success(request, '✅ Mot de passe mis à jour avec succès.')
                    
                    # ========== 🔔 إشعار للأدمن ==========
                    from .utils import notify_admin_password_change
                    notify_admin_password_change(user)
                    # =====================================
                else:
                    messages.error(request, '❌ Le mot de passe doit contenir au moins 8 caractères.')
            else:
                messages.error(request, '❌ Les mots de passe ne correspondent pas.')
        
        user.save()
        return redirect('user_profile')
    
    return render(request, 'inventory/user_profile.html')

# ========== PRODUCT MANAGEMENT ==========
@staff_or_superuser_required
@login_required(login_url='login')
def produit_list(request):
    produits = Produit.objects.all().order_by('designation')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        produits = produits.filter(
            Q(code_p__icontains=search_query) |
            Q(designation__icontains=search_query)
        )
    return render(request, 'inventory/produit_list.html', {'produits': produits, 'search_query': search_query})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def app_home(request):
    return render(request, 'inventory/app.html')


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def produit_create(request):
    if request.method == 'POST':
        form = ProduitForm(request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse('produit_list'))
    else:
        form = ProduitForm()
    return render(request, 'inventory/produit_form.html', {'form': form, 'title': 'Ajouter un produit'})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def produit_edit(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    if request.method == 'POST':
        form = ProduitForm(request.POST, instance=produit)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse('produit_list'))
    else:
        form = ProduitForm(instance=produit)
    return render(request, 'inventory/produit_form.html', {'form': form, 'title': 'Modifier le produit'})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def produit_delete(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    if request.method == 'POST':
        try:
            produit.delete()
            messages.success(request, f"Produit '{produit.designation}' supprimé avec succès.")
            return redirect('produit_list')
        except ProtectedError:
            messages.error(request, f"Impossible de supprimer '{produit.designation}' car il est référencé dans des lignes d'entrée ou de sortie.")
            return redirect('produit_list')
    return render(request, 'inventory/produit_confirm_delete.html', {'produit': produit})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def produit_history(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    entrees = LigneEntree.objects.filter(produit=produit).select_related('bon', 'bon__fournisseur', 'bon__utilisateur')
    sorties = LigneSortie.objects.filter(produit=produit).select_related('bon', 'bon__client', 'bon__utilisateur')
    
    history = []
    for ligne in entrees:
        history.append({
            'type': 'Entrée',
            'date': ligne.bon.date_e,
            'quantity': ligne.qte_e,
            'counterparty': ligne.bon.fournisseur.designation,
            'user': ligne.bon.utilisateur.user.username,
            'bon_num': ligne.bon.num_e,
        })
    for ligne in sorties:
        history.append({
            'type': 'Sortie',
            'date': ligne.bon.date_s,
            'quantity': ligne.qte_s,
            'counterparty': ligne.bon.client.designation,
            'user': ligne.bon.utilisateur.user.username,
            'bon_num': ligne.bon.num_s,
        })
    history.sort(key=lambda x: x['date'], reverse=True)
    return render(request, 'inventory/history_produit.html', {'produit': produit, 'history': history})


# ========== PRODUCT API ==========
@staff_or_superuser_required
@login_required(login_url='login')
def product_list_api(request):
    produits = Produit.objects.all().values('code_p', 'designation', 'qte_stock', 'stock_alerte')
    return JsonResponse({'produits': list(produits)})


@csrf_exempt
@login_required(login_url='login')
@staff_or_superuser_required
@require_http_methods(['GET', 'POST'])
def produit_api(request):
    if request.method == 'GET':
        produits = Produit.objects.all().values('code_p', 'designation', 'qte_stock', 'stock_alerte')
        return JsonResponse({'produits': list(produits)})

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return HttpResponseBadRequest('JSON invalide')

    designation = data.get('designation')
    qte_stock = data.get('qte_stock')
    stock_alerte = data.get('stock_alerte')

    if designation is None or qte_stock is None or stock_alerte is None:
        return HttpResponseBadRequest('Champs manquants')

    produit = Produit.objects.create(designation=designation, qte_stock=qte_stock, stock_alerte=stock_alerte)
    return JsonResponse({
        'code_p': produit.code_p,
        'designation': produit.designation,
        'qte_stock': produit.qte_stock,
        'stock_alerte': produit.stock_alerte
    }, status=201)


@csrf_exempt
@login_required(login_url='login')
@staff_or_superuser_required
@require_http_methods(['PUT', 'DELETE'])
def produit_api_detail(request, pk):
    produit = get_object_or_404(Produit, pk=pk)

    if request.method == 'DELETE':
        produit.delete()
        return HttpResponse(status=204)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return HttpResponseBadRequest('JSON invalide')

    designation = data.get('designation')
    qte_stock = data.get('qte_stock')
    stock_alerte = data.get('stock_alerte')

    if designation is not None:
        produit.designation = designation
    if qte_stock is not None:
        produit.qte_stock = qte_stock
    if stock_alerte is not None:
        produit.stock_alerte = stock_alerte

    produit.save()
    return JsonResponse({
        'code_p': produit.code_p,
        'designation': produit.designation,
        'qte_stock': produit.qte_stock,
        'stock_alerte': produit.stock_alerte
    })


# ========== CLIENT MANAGEMENT ==========
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def client_list(request):
    clients = Client.objects.all().order_by('designation')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        clients = clients.filter(
            Q(code_cl__icontains=search_query) |
            Q(designation__icontains=search_query) |
            Q(tel__icontains=search_query)
        )
    return render(request, 'inventory/client_list.html', {'clients': clients, 'search_query': search_query})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def client_create(request):
    if request.method == 'POST':
        designation = request.POST.get('designation', '').strip()
        tel = request.POST.get('tel', '').strip()
        if designation:
            Client.objects.create(designation=designation, tel=tel)
            return redirect('client_list')
        return render(request, 'inventory/client_form.html', {'error': 'Veuillez saisir le nom du client.'})
    return render(request, 'inventory/client_form.html')


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        designation = request.POST.get('designation', '').strip()
        tel = request.POST.get('tel', '').strip()
        if designation:
            client.designation = designation
            client.tel = tel
            client.save()
            return redirect('client_list')
        return render(request, 'inventory/client_form.html', {'client': client, 'error': 'Veuillez saisir le nom du client.'})
    return render(request, 'inventory/client_form.html', {'client': client})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        client.delete()
        messages.success(request, f"Client '{client.designation}' supprimé avec succès.")
        return redirect('client_list')
    return render(request, 'inventory/client_confirm_delete.html', {'client': client})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def client_history(request, pk):
    client = get_object_or_404(Client, pk=pk)
    bons = BonSortie.objects.filter(client=client).prefetch_related('lignes__produit').order_by('-date_s')
    return render(request, 'inventory/history_client.html', {'client': client, 'bons': bons})


# ========== FOURNISSEUR MANAGEMENT ==========
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def fournisseur_list(request):
    fournisseurs = Fournisseur.objects.all().order_by('designation')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        fournisseurs = fournisseurs.filter(
            Q(num_f__icontains=search_query) |
            Q(designation__icontains=search_query) |
            Q(tel__icontains=search_query)
        )
    return render(request, 'inventory/fournisseur_list.html', {'fournisseurs': fournisseurs, 'search_query': search_query})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def fournisseur_create(request):
    if request.method == 'POST':
        designation = request.POST.get('designation', '').strip()
        tel = request.POST.get('tel', '').strip()
        if designation:
            Fournisseur.objects.create(designation=designation, tel=tel)
            return redirect('fournisseur_list')
        return render(request, 'inventory/fournisseur_form.html', {'error': 'Veuillez saisir le nom du fournisseur.'})
    return render(request, 'inventory/fournisseur_form.html')


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def fournisseur_edit(request, pk):
    fournisseur = get_object_or_404(Fournisseur, pk=pk)
    if request.method == 'POST':
        designation = request.POST.get('designation', '').strip()
        tel = request.POST.get('tel', '').strip()
        if designation:
            fournisseur.designation = designation
            fournisseur.tel = tel
            fournisseur.save()
            return redirect('fournisseur_list')
        return render(request, 'inventory/fournisseur_form.html', {'fournisseur': fournisseur, 'error': 'Veuillez saisir le nom du fournisseur.'})
    return render(request, 'inventory/fournisseur_form.html', {'fournisseur': fournisseur})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def fournisseur_delete(request, pk):
    fournisseur = get_object_or_404(Fournisseur, pk=pk)
    if request.method == 'POST':
        fournisseur.delete()
        messages.success(request, f"Fournisseur '{fournisseur.designation}' supprimé avec succès.")
        return redirect('fournisseur_list')
    return render(request, 'inventory/fournisseur_confirm_delete.html', {'fournisseur': fournisseur})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def fournisseur_history(request, pk):
    fournisseur = get_object_or_404(Fournisseur, pk=pk)
    bons = BonEntree.objects.filter(fournisseur=fournisseur).prefetch_related('lignes__produit').order_by('-date_e')
    return render(request, 'inventory/history_fournisseur.html', {'fournisseur': fournisseur, 'bons': bons})


# ========== USER MANAGEMENT ==========
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def user_list(request):
    users = User.objects.all().order_by('username')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    return render(request, 'inventory/user_list.html', {'users': users, 'search_query': search_query})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def admin_create_user(request):
    if request.method == 'POST':
        form = AdminUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits
            temp_password = ''.join(secrets.choice(alphabet) for _ in range(10))
            user.set_password(temp_password)
            user.save()
            
            profil, created = Utilisateur.objects.get_or_create(
                user=user,
                defaults={
                    'must_change_password': True,
                    'role': 'staff',
                    'tel': '',
                    'is_banned': False,
                    'failed_login_attempts': 0
                }
            )
            
            # ========== 🔔 إرسال الإيميل ==========
            from .utils import send_welcome_email
            send_welcome_email(user, temp_password)
            # =====================================
            
            messages.success(request, f"✅ Utilisateur '{user.username}' créé.")
            return redirect('user_list')
    else:
        form = AdminUserCreationForm()
    return render(request, 'inventory/admin_create_user.html', {'form': form})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def user_edit_secure(request, pk):
    user = get_object_or_404(User, pk=pk)
    # تأكد من وجود البروفايل
    profil, created = Utilisateur.objects.get_or_create(
        user=user,
        defaults={
            'must_change_password': False,
            'role': 'staff' if user.is_staff else 'user',
            'tel': '',
            'is_banned': False,
            'failed_login_attempts': 0
        }
    )
    
    if request.method == 'POST':
        user.email = request.POST.get('email')
        user.first_name = request.POST.get('first_name', '')
        user.last_name = request.POST.get('last_name', '')
        user.save()
        
        new_role = request.POST.get('role')
        if new_role in ['admin', 'staff', 'user']:
            profil.role = new_role
            user.is_staff = (new_role in ['admin', 'staff'])
            user.is_superuser = (new_role == 'admin')
            user.save()
        
        profil.save()
        messages.success(request, f"✅ Informations de '{user.username}' mises à jour.")
        return redirect('user_list')
    
    return render(request, 'inventory/user_form.html', {
        'form': AdminUserCreationForm(instance=user),
        'title': f"Modifier l'utilisateur - {user.username}",
        'edit_user': user,
        'profil': profil
    })

@user_passes_test(lambda u: u.is_superuser, login_url='login')
def toggle_user_ban(request, user_id):
    profil = get_object_or_404(Utilisateur, id=user_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        duration = request.POST.get('duration')
        
        if action == 'ban':
            profil.is_banned = True
            if duration and duration.isdigit():
                profil.ban_until = timezone.now() + timezone.timedelta(minutes=int(duration))
            else:
                profil.ban_until = None
            messages.success(request, f"✅ Utilisateur '{profil.user.username}' a été banni.")
        
        elif action == 'unban':
            profil.is_banned = False
            profil.ban_until = None
            profil.failed_login_attempts = 0
            messages.success(request, f"✅ Utilisateur '{profil.user.username}' a été débanni.")
        
        profil.save()
        return redirect('user_list')
    
    return render(request, 'inventory/toggle_user_ban.html', {'profil': profil})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def user_history(request, username):
    user_obj = get_object_or_404(User, username=username)
    profil = get_object_or_404(Utilisateur, user=user_obj)
    
    entrees = BonEntree.objects.filter(utilisateur=profil).order_by('-date_e')
    sorties = BonSortie.objects.filter(utilisateur=profil).order_by('-date_s')
    return render(request, 'inventory/history_user.html', {'user_obj': user_obj, 'entrees': entrees, 'sorties': sorties})


# ========== BON ENTRÉE ==========
@staff_or_superuser_required
@login_required(login_url='login')
def bon_entree_list(request):
    if request.user.is_superuser:
        bons = BonEntree.objects.all().order_by('-date_e')
    else:
        utilisateur_obj = request.user.profil
        bons = BonEntree.objects.filter(utilisateur=utilisateur_obj).order_by('-date_e')
    
    search_query = request.GET.get('q', '').strip()
    if search_query:
        bons = bons.filter(
            Q(num_e__icontains=search_query) |
            Q(fournisseur__designation__icontains=search_query) |
            Q(utilisateur__user__username__icontains=search_query)
        )
    return render(request, 'inventory/bon_entree_list.html', {'bons': bons, 'search_query': search_query})


@staff_or_superuser_required
@login_required(login_url='login')
def bon_entree_create(request):
    fournisseurs = Fournisseur.objects.all()
    produits = Produit.objects.all()

    if request.method == 'POST':
        fournisseur_id = request.POST.get('fournisseur')
        produits_ids = request.POST.getlist('produit[]')
        qtes = request.POST.getlist('qte[]')

        if not fournisseur_id:
            messages.error(request, '❌ Veuillez sélectionner un fournisseur.')
            return render(request, 'inventory/bon_entree_form.html', {
                'fournisseurs': fournisseurs,
                'produits': produits,
            })

        fournisseur = Fournisseur.objects.filter(pk=fournisseur_id).first()
        if not fournisseur:
            messages.error(request, '❌ Fournisseur introuvable.')
            return render(request, 'inventory/bon_entree_form.html', {
                'fournisseurs': fournisseurs,
                'produits': produits,
            })

        if not produits_ids or not qtes or len(produits_ids) != len(qtes):
            messages.error(request, '❌ Veuillez ajouter au moins un produit avec sa quantité.')
            return render(request, 'inventory/bon_entree_form.html', {
                'fournisseurs': fournisseurs,
                'produits': produits,
            })

        utilisateur_obj = request.user.profil

        lignes_data = []
        errors = []

        for i in range(len(produits_ids)):
            prod_id = produits_ids[i]
            qte_str = qtes[i]
            
            if not prod_id or not qte_str:
                continue
                
            try:
                qte = int(qte_str)
            except ValueError:
                errors.append(f"❌ Quantité invalide pour le produit n°{i+1}.")
                continue

            if qte <= 0:
                errors.append(f"❌ La quantité du produit n°{i+1} doit être supérieure à zéro.")
                continue

            produit = Produit.objects.filter(pk=prod_id).first()
            if not produit:
                errors.append(f"❌ Produit n°{i+1} introuvable.")
                continue

            lignes_data.append((produit, qte))

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'inventory/bon_entree_form.html', {
                'fournisseurs': fournisseurs,
                'produits': produits,
            })

        if lignes_data:
            bon = BonEntree.objects.create(
                fournisseur=fournisseur,
                utilisateur=utilisateur_obj,
                date_e=timezone.now()
            )

            for produit, qte in lignes_data:
                LigneEntree.objects.create(bon=bon, produit=produit, qte_e=qte)
                produit.qte_stock += qte
                produit.save()

            messages.success(request, f'✅ Bon d\'entrée #{bon.num_e} créé avec succès ! {len(lignes_data)} produit(s) ajouté(s).')
            return redirect('bon_entree_list')
        else:
            messages.error(request, '❌ Aucune ligne valide à enregistrer.')

    return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})


@login_required(login_url='login')
def bon_entree_detail(request, pk):
    bon = get_object_or_404(BonEntree, pk=pk)
    if not request.user.is_superuser and bon.utilisateur.user != request.user:
        return HttpResponseForbidden("Vous n'avez pas accès à ce bon.")
    lignes = bon.lignes.all()
    return render(request, 'inventory/bon_entree_detail.html', {'bon': bon, 'lignes': lignes})


@login_required(login_url='login')
def bon_entree_delete(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Seuls les administrateurs peuvent supprimer des bons d'entrée.")
    bon = get_object_or_404(BonEntree, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            for ligne in bon.lignes.all():
                produit = ligne.produit
                produit.qte_stock -= ligne.qte_e
                produit.save()
            bon.delete()
        messages.success(request, f"✅ Bon d'entrée #{pk} supprimé avec succès.")
        return redirect('bon_entree_list')
    return render(request, 'inventory/bon_entree_confirm_delete.html', {'bon': bon})


# ========== BON SORTIE ==========
@staff_or_superuser_required
@login_required(login_url='login')
def bon_sortie_list(request):
    if request.user.is_superuser:
        bons = BonSortie.objects.all().order_by('-date_s')
    else:
        utilisateur_obj = request.user.profil
        bons = BonSortie.objects.filter(utilisateur=utilisateur_obj).order_by('-date_s')
    
    search_query = request.GET.get('q', '').strip()
    if search_query:
        bons = bons.filter(
            Q(num_s__icontains=search_query) |
            Q(client__designation__icontains=search_query) |
            Q(utilisateur__user__username__icontains=search_query)
        )
    return render(request, 'inventory/bon_sortie_list.html', {'bons': bons, 'search_query': search_query})


@staff_or_superuser_required
@login_required(login_url='login')
def bon_sortie_create(request):
    clients = Client.objects.all()
    produits = Produit.objects.all()

    if request.method == 'POST':
        client_id = request.POST.get('client')
        produits_ids = request.POST.getlist('produit[]')
        qtes = request.POST.getlist('qte[]')

        if not client_id:
            messages.error(request, '❌ Veuillez sélectionner un client.')
            return render(request, 'inventory/bon_sortie_form.html', {
                'clients': clients,
                'produits': produits,
            })
        client = Client.objects.filter(pk=client_id).first()
        if not client:
            messages.error(request, '❌ Client introuvable.')
            return render(request, 'inventory/bon_sortie_form.html', {
                'clients': clients,
                'produits': produits,
            })
        if not produits_ids or not qtes or len(produits_ids) != len(qtes):
            messages.error(request, '❌ Veuillez ajouter au moins un produit avec sa quantité.')
            return render(request, 'inventory/bon_sortie_form.html', {
                'clients': clients,
                'produits': produits,
            })

        utilisateur_obj = request.user.profil

        low_stock_products_names = []
        lignes_data = []
        errors = []

        for i in range(len(produits_ids)):
            prod_id = produits_ids[i]
            qte_str = qtes[i]
            if not prod_id or not qte_str:
                continue
            try:
                qte = int(qte_str)
            except ValueError:
                errors.append(f"❌ Quantité invalide pour le produit n°{i+1}.")
                continue
            produit = Produit.objects.filter(pk=prod_id).first()
            if not produit:
                errors.append(f"❌ Produit n°{i+1} introuvable.")
                continue
            if qte <= 0:
                errors.append(f"❌ La quantité du produit '{produit.designation}' doit être supérieure à zéro.")
                continue
            if qte > produit.qte_stock:
                errors.append(f"❌ Quantité insuffisante pour '{produit.designation}'. Stock disponible: {produit.qte_stock}.")
                continue
            lignes_data.append((produit, qte))

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'inventory/bon_sortie_form.html', {
                'clients': clients,
                'produits': produits,
            })

        bon = BonSortie.objects.create(
            client=client,
            utilisateur=utilisateur_obj,
            date_s=timezone.now()
        )
        for produit, qte in lignes_data:
            LigneSortie.objects.create(bon=bon, produit=produit, qte_s=qte)
            produit.qte_stock -= qte
            produit.save()
            if produit.qte_stock <= produit.stock_alerte:
                low_stock_products_names.append(produit.designation)

        if low_stock_products_names:
            message = f"⚠️ Stock faible pour : {', '.join(low_stock_products_names)}"
            messages.add_message(request, LOW_STOCK, message)

        messages.success(request, f'✅ Bon de sortie #{bon.num_s} créé avec succès ! {len(lignes_data)} produit(s) retiré(s).')
        return redirect('bon_sortie_detail', pk=bon.pk)

    return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})


@login_required(login_url='login')
def bon_sortie_detail(request, pk):
    bon = get_object_or_404(BonSortie, pk=pk)
    if not request.user.is_superuser and bon.utilisateur.user != request.user:
        return HttpResponseForbidden("Vous n'avez pas accès à ce bon.")
    lignes = bon.lignes.all()
    return render(request, 'inventory/bon_sortie_detail.html', {'bon': bon, 'lignes': lignes})


@login_required(login_url='login')
def bon_sortie_delete(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Seuls les administrateurs peuvent supprimer des bons de sortie.")
    bon = get_object_or_404(BonSortie, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            for ligne in bon.lignes.all():
                produit = ligne.produit
                produit.qte_stock += ligne.qte_s
                produit.save()
            bon.delete()
        messages.success(request, f"✅ Bon de sortie #{pk} supprimé avec succès.")
        return redirect('bon_sortie_list')
    return render(request, 'inventory/bon_sortie_confirm_delete.html', {'bon': bon})


# ========== ADMIN REPORT ==========
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def admin_report(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    entrees = BonEntree.objects.none()
    sorties = BonSortie.objects.none()
    stats = {
        'total_entrees': 0,
        'total_sorties': 0,
    }
    top_products = []
    top_fournisseurs = []
    top_clients = []
    error = None

    if start_date and end_date:
        try:
            start = parse_date(start_date)
            end = parse_date(end_date)
            if start and end:
                entrees = BonEntree.objects.filter(date_e__date__gte=start, date_e__date__lte=end).order_by('-date_e')
                sorties = BonSortie.objects.filter(date_s__date__gte=start, date_s__date__lte=end).order_by('-date_s')
                
                stats['total_entrees'] = entrees.count()
                stats['total_sorties'] = sorties.count()
                
                # TOP PRODUITS
                product_entries = LigneEntree.objects.filter(bon__in=entrees).values('produit__code_p', 'produit__designation').annotate(total_in=Sum('qte_e'))
                product_exits = LigneSortie.objects.filter(bon__in=sorties).values('produit__code_p', 'produit__designation').annotate(total_out=Sum('qte_s'))
                
                product_totals = {}
                for p in product_entries:
                    product_totals[p['produit__code_p']] = {
                        'designation': p['produit__designation'],
                        'total_in': p['total_in'],
                        'total_out': 0,
                    }
                for p in product_exits:
                    code = p['produit__code_p']
                    if code in product_totals:
                        product_totals[code]['total_out'] = p['total_out']
                    else:
                        product_totals[code] = {
                            'designation': p['produit__designation'],
                            'total_in': 0,
                            'total_out': p['total_out'],
                        }
                for code, data in product_totals.items():
                    data['total_moved'] = data['total_in'] + data['total_out']
                top_products = sorted(product_totals.values(), key=lambda x: x['total_out'], reverse=True)[:5]
                
                # TOP FOURNISSEURS
                fournisseur_totals = LigneEntree.objects.filter(bon__in=entrees).values(
                    'bon__fournisseur__num_f', 'bon__fournisseur__designation'
                ).annotate(total_qte=Sum('qte_e')).order_by('-total_qte')[:5]
                
                top_fournisseurs = []
                for f in fournisseur_totals:
                    fournisseur_num = f['bon__fournisseur__num_f']
                    fournisseur_name = f['bon__fournisseur__designation']
                    total_qte = f['total_qte']
                    
                    products = LigneEntree.objects.filter(
                        bon__in=entrees,
                        bon__fournisseur__num_f=fournisseur_num
                    ).values('produit__designation').annotate(qte=Sum('qte_e')).order_by('-qte')[:5]
                    
                    top_fournisseurs.append({
                        'num': fournisseur_num,
                        'name': fournisseur_name,
                        'total_qte': total_qte,
                        'products': list(products),
                    })
                
                # TOP CLIENTS
                client_totals = LigneSortie.objects.filter(bon__in=sorties).values(
                    'bon__client__code_cl', 'bon__client__designation'
                ).annotate(total_qte=Sum('qte_s')).order_by('-total_qte')[:5]
                
                top_clients = []
                for c in client_totals:
                    client_code = c['bon__client__code_cl']
                    client_name = c['bon__client__designation']
                    total_qte = c['total_qte']
                    
                    products = LigneSortie.objects.filter(
                        bon__in=sorties,
                        bon__client__code_cl=client_code
                    ).values('produit__designation').annotate(qte=Sum('qte_s')).order_by('-qte')[:5]
                    
                    top_clients.append({
                        'code': client_code,
                        'name': client_name,
                        'total_qte': total_qte,
                        'products': list(products),
                    })
            else:
                error = "Format de date invalide. Utilisez YYYY-MM-DD."
        except Exception as e:
            error = f"Erreur: {str(e)}"
    elif start_date or end_date:
        error = "Veuillez fournir les deux dates (début et fin)."

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'entrees': entrees,
        'sorties': sorties,
        'stats': stats,
        'top_products': top_products,
        'top_fournisseurs': top_fournisseurs,
        'top_clients': top_clients,
        'error': error,
    }
    return render(request, 'inventory/admin_report.html', context)


# ========== DATA DASHBOARD ==========
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def data_dashboard(request):
    stats = {
        'fournisseurs': Fournisseur.objects.count(),
        'clients': Client.objects.count(),
        'produits': Produit.objects.count(),
        'bons_entree': BonEntree.objects.count(),
        'bons_sortie': BonSortie.objects.count(),
        'utilisateurs': Utilisateur.objects.count(),
    }
    return render(request, 'inventory/data_dashboard.html', {'stats': stats})
# ========== DELETE USER ==========
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def delete_user(request, pk):
    """Supprimer un utilisateur (superuser seulement)"""
    user = get_object_or_404(User, pk=pk)
    
    # Ne pas permettre la suppression de son propre compte
    if user == request.user:
        messages.error(request, "❌ Vous ne pouvez pas supprimer votre propre compte.")
        return redirect('user_list')
    
    # Ne pas permettre la suppression du dernier superuser
    if user.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
        messages.error(request, "❌ Impossible de supprimer le dernier administrateur.")
        return redirect('user_list')
    
    if request.method == 'POST':
        username = user.username
        # Supprimer le profil Utilisateur associé
        if hasattr(user, 'profil'):
            user.profil.delete()
        user.delete()
        messages.success(request, f"✅ Utilisateur '{username}' supprimé avec succès.")
        return redirect('user_list')
    
    return render(request, 'inventory/user_confirm_delete.html', {'user_obj': user})


# ========== USER CREATE (alternative) ==========
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def user_create(request):
    if request.method == 'POST':
        form = AdminUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits
            temp_password = ''.join(secrets.choice(alphabet) for _ in range(10))
            user.set_password(temp_password)
            user.save()
            
            # إنشاء البروفايل
            profil, created = Utilisateur.objects.get_or_create(
                user=user,
                defaults={
                    'must_change_password': True,
                    'role': 'staff',
                    'tel': '',
                    'is_banned': False,
                    'failed_login_attempts': 0
                }
            )
            
            # ========== 🔔 هنا نضيف إرسال الإيميل ==========
            from .utils import send_welcome_email
            send_welcome_email(user, temp_password)
            # =============================================
            
            # تخزين كلمة السر المؤقتة في session
            request.session['temp_password'] = temp_password
            request.session['new_user_id'] = user.id
            
            return redirect('user_created_info')
    else:
        form = AdminUserCreationForm()
    return render(request, 'inventory/user_form.html', {'form': form, 'title': 'Ajouter un utilisateur'})

# ========== USER EDIT ==========
@user_passes_test(lambda u: u.is_superuser, login_url='login')
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    profil = get_object_or_404(Utilisateur, user=user)
    
    if request.method == 'POST':
        # L'admin peut modifier, mais PAS le mot de passe
        user.email = request.POST.get('email')
        user.first_name = request.POST.get('first_name', '')
        user.last_name = request.POST.get('last_name', '')
        user.save()
        
        # Modifier le rôle
        new_role = request.POST.get('role')
        if new_role in ['admin', 'staff', 'user']:
            profil.role = new_role
            # Mettre à jour is_staff et is_superuser
            user.is_staff = (new_role in ['admin', 'staff'])
            user.is_superuser = (new_role == 'admin')
            user.save()
        
        profil.save()
        messages.success(request, f"✅ Informations de '{user.username}' mises à jour.")
        return redirect('user_list')
    
    return render(request, 'inventory/user_form.html', {
        'form': AdminUserCreationForm(instance=user),
        'title': f"Modifier l'utilisateur - {user.username}",
        'edit_user': user,
        'profil': profil
    })


# ========== LOGOUT ==========
def custom_logout(request):
    logout(request)
    messages.success(request, "✅ Vous avez été déconnecté avec succès.")
    return redirect('login')

from django.utils import timezone

@user_passes_test(lambda u: u.is_superuser, login_url='login')
def user_created_info(request):
    user_id = request.session.get('new_user_id')
    temp_password = request.session.get('temp_password')
    
    if not user_id or not temp_password:
        return redirect('user_list')
    
    user = get_object_or_404(User, pk=user_id)
    
    # مسح الجلسة بعد العرض
    del request.session['new_user_id']
    del request.session['temp_password']
    
    return render(request, 'inventory/user_created_info.html', {
        'user': user,
        'temp_password': temp_password,
        'now': timezone.now()
    })