import json
import secrets
import string
import pyotp
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
from django.core.cache import cache
import uuid
import secrets
from .utils import send_email_to_user
from .models import (
    Entreprise, Produit, Utilisateur, Fournisseur, 
    Client, BonEntree, LigneEntree, BonSortie, LigneSortie, 
    NotificationStatus, Notification  # ✅ أضف Notification هنا
)

from .forms import AdminUserCreationForm, ProduitForm, ForcePasswordChangeForm, ForgotPasswordForm, ResetPasswordForm, AdminOTPForm
from .models import (
    Entreprise, Produit, Utilisateur, Fournisseur, 
    Client, BonEntree, LigneEntree, BonSortie, LigneSortie, NotificationStatus
)
from .utils import send_welcome_email, notify_admin_password_change, notify_admin_forgot_password

LOW_STOCK = 50


# ========== DECORATORS ==========
def staff_or_superuser_required(view_func):
    actual_decorator = user_passes_test(
        lambda u: u.is_authenticated and (u.is_staff or u.is_superuser),
        login_url='waiting_room',
        redirect_field_name=None
    )
    return actual_decorator(view_func)


def get_user_profile(user):
    try:
        return user.profil
    except Exception:
        profil = Utilisateur.objects.create(
            user=user,
            must_change_password=False,
            role='admin' if user.is_superuser else ('staff' if user.is_staff else 'user'),
            tel='',
            is_banned=False,
            failed_login_attempts=0
        )
        return profil


# ========== AUTHENTIFICATION ==========
def custom_login(request):
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Vérifier si l'utilisateur existe
        try:
            user_obj = User.objects.get(username=username)
            if hasattr(user_obj, 'profil'):
                # ✅ تحديث حالة الحظر أولاً
                user_obj.profil.update_ban_status()
                
                is_locked, lock_message = user_obj.profil.is_account_locked()
                if is_locked:
                    messages.error(request, f"🔒 {lock_message}")
                    return redirect('login')
        except User.DoesNotExist:
            pass
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if hasattr(user, 'profil'):
                user.profil.reset_failed_attempts()
            
            request.session['pre_otp_user_id'] = user.id
            
            profil = get_user_profile(user)
            if not profil.otp_secret:
                profil.otp_secret = pyotp.random_base32()
                profil.save()
            
            totp = pyotp.TOTP(profil.otp_secret)
            otp_code = totp.now()
            
            request.session['login_otp'] = otp_code
            request.session['login_otp_expires'] = (timezone.now() + timezone.timedelta(minutes=5)).timestamp()
            
            try:
                send_mail(
                    'Code de verification OTP',
                    f'Bonjour {user.username},\n\nVotre code OTP pour vous connecter est : {otp_code}\n\nCe code expire dans 5 minutes.',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=True,
                )
            except:
                pass
            
            return redirect('verify_login_otp')
        else:
            try:
                user_obj = User.objects.get(username=username)
                if hasattr(user_obj, 'profil'):
                    user_obj.profil.increment_failed_attempts()
            except User.DoesNotExist:
                pass
            messages.error(request, "Nom d'utilisateur ou mot de passe incorrect.")
    
    return render(request, 'inventory/login.html')


def verify_login_otp(request):
    user_id = request.session.get('pre_otp_user_id')
    
    if not user_id:
        return redirect('login')
    
    user = get_object_or_404(User, pk=user_id)
    
    stored_otp = request.session.get('login_otp')
    expires = request.session.get('login_otp_expires', 0)
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "Code OTP expiré")
        return redirect('login')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if otp_code == stored_otp:
            login(request, user)
            
            for key in ['pre_otp_user_id', 'login_otp', 'login_otp_expires']:
                if key in request.session:
                    del request.session[key]
            
            if hasattr(user, 'profil') and user.profil.must_change_password:
                messages.info(request, "Veuillez changer votre mot de passe temporaire")
                return redirect('request_otp_for_password_change')
            
            return redirect('home')
        else:
            messages.error(request, "Code OTP invalide")
    
    return render(request, 'inventory/verify_otp.html', {'username': user.username})


def custom_logout(request):
    logout(request)
    messages.success(request, "Vous avez ete deconnecte avec succes.")
    return redirect('login')


@login_required
def force_password_change(request):
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
            
            update_session_auth_hash(request, request.user)
            
            messages.success(request, "Votre mot de passe a ete change avec succes.")
            return redirect('home')
    else:
        form = ForcePasswordChangeForm()
    
    return render(request, 'inventory/force_password_change.html', {'form': form})


def forgot_password(request):
    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = User.objects.get(email=email)
                if hasattr(user, 'profil'):
                    profil = user.profil
                    
                    token = secrets.token_urlsafe(32)
                    profil.reset_password_token = token
                    profil.reset_token_expires = timezone.now() + timezone.timedelta(hours=24)
                    profil.save()
                    
                    reset_link = request.build_absolute_uri(reverse('reset_password', args=[token]))
                    
                    try:
                        send_mail(
                            'Reinitialisation de votre mot de passe',
                            f'Bonjour {user.username},\n\nCliquez sur le lien suivant :\n{reset_link}\n\nCe lien expire dans 24 heures.',
                            settings.DEFAULT_FROM_EMAIL,
                            [email],
                            fail_silently=True,
                        )
                    except:
                        pass
                    
                    notify_admin_forgot_password(user)
                    
                    messages.success(request, "Un email de reinitialisation a ete envoye.")
            except User.DoesNotExist:
                messages.success(request, "Si cet email existe, un lien de reinitialisation a ete envoye.")
            return redirect('login')
    else:
        form = ForgotPasswordForm()
    return render(request, 'inventory/forgot_password.html', {'form': form})


def reset_password(request, token):
    try:
        profil = Utilisateur.objects.get(reset_password_token=token, reset_token_expires__gt=timezone.now())
        user = profil.user
    except Utilisateur.DoesNotExist:
        messages.error(request, "Lien invalide ou expire.")
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
            
            messages.success(request, "Votre mot de passe a ete reinitialise.")
            return redirect('login')
    else:
        form = ResetPasswordForm()
    
    return render(request, 'inventory/reset_password.html', {'form': form, 'token': token})


# ========== OTP PASSWORD CHANGE AFTER LOGIN ==========

@login_required
def change_password_otp_verify(request):
    """التحقق من OTP وتغيير كلمة السر"""
    stored_otp = request.session.get('change_pw_otp')
    expires = request.session.get('change_pw_otp_expires', 0)
    new_password = request.session.get('new_password')
    
    # ✅ التحقق من وجود البيانات
    if not stored_otp:
        messages.error(request, "Session expirée, veuillez recommencer")
        return redirect('change_password_request')
    
    if not new_password:
        messages.error(request, "Session expirée, veuillez recommencer")
        return redirect('change_password_request')
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "Code OTP expiré, veuillez recommencer")
        return redirect('change_password_request')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if otp_code != stored_otp:
            messages.error(request, "Code OTP invalide")
            return redirect('change_password_otp_verify')
        
        # OTP correct, changer le mot de passe
        user = request.user
        user.set_password(new_password)
        user.save()
        
        if hasattr(user, 'profil'):
            user.profil.must_change_password = False
            user.profil.password_changed_at = timezone.now()
            user.profil.save()
        
        # ✅ Nettoyer la session
        session_keys = ['change_pw_otp', 'change_pw_otp_expires', 'new_password']
        for key in session_keys:
            if key in request.session:
                del request.session[key]
        
        update_session_auth_hash(request, user)
        
        from .utils import notify_admin_password_change
        notify_admin_password_change(user)
        
        messages.success(request, "Votre mot de passe a été changé avec succès")
        return redirect('user_profile')
    
    return render(request, 'inventory/change_password_otp_verify.html')

def change_password_with_otp_after_login(request):
    if not request.user.is_authenticated:
        return redirect('login')
    
    stored_otp = request.session.get('change_pw_otp')
    expires = request.session.get('change_pw_otp_expires', 0)
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "Code OTP expire")
        return redirect('request_otp_for_password_change')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if otp_code != stored_otp:
            messages.error(request, "Code OTP invalide")
            return render(request, 'inventory/change_password_otp.html', {'require_otp': True})
        
        if new_password != confirm_password:
            messages.error(request, "Les mots de passe ne correspondent pas")
            return render(request, 'inventory/change_password_otp.html', {'require_otp': False})
        
        if len(new_password) < 8:
            messages.error(request, "8 caracteres minimum")
            return render(request, 'inventory/change_password_otp.html', {'require_otp': False})
        
        user = request.user
        user.set_password(new_password)
        user.save()
        
        if hasattr(user, 'profil'):
            user.profil.must_change_password = False
            user.profil.password_changed_at = timezone.now()
            user.profil.save()
        
        for key in ['change_pw_otp', 'change_pw_otp_expires']:
            if key in request.session:
                del request.session[key]
        
        update_session_auth_hash(request, user)
        
        messages.success(request, "Votre mot de passe a ete change avec succes")
        return redirect('home')
    
    return render(request, 'inventory/change_password_otp.html', {'require_otp': True})


# ========== HOME & DASHBOARDS ==========
def home(request):
    if request.user.is_superuser:
        return redirect('dashboard_admin')
    if not request.user.is_staff:
        return redirect('waiting_room')
    return redirect('dashboard_user')


def waiting_room(request):
    return render(request, 'inventory/waiting_room.html')


@login_required
def dashboard_admin(request):
    if not request.user.is_superuser:
        return redirect('dashboard_user')
    
    get_user_profile(request.user)
    
    today = timezone.now()
    first_day = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    entrees_mois = BonEntree.objects.filter(date_e__gte=first_day).count()
    sorties_mois = BonSortie.objects.filter(date_s__gte=first_day).count()
    total_produits = Produit.objects.count()
    low_stock = Produit.objects.filter(qte_stock__lte=F('stock_alerte')).count()
    
    dernieres_entrees = BonEntree.objects.order_by('-date_e')[:5]
    dernieres_sorties = BonSortie.objects.order_by('-date_s')[:5]
    mouvements = []
    for e in dernieres_entrees:
        total_qte = e.lignes.aggregate(s=Sum('qte_e'))['s'] or 0
        mouvements.append({
            'designation': f"Entree #{e.num_e} - {e.fournisseur.designation}",
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
@login_required
def dashboard_user(request):
    if request.user.is_superuser:
        return redirect('dashboard_admin')
    if not request.user.is_staff:
        return redirect('waiting_room')
    
    utilisateur_obj = get_user_profile(request.user)
    
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
                    messages.success(request, 'Mot de passe mis a jour.')
                    notify_admin_password_change(user)
                else:
                    messages.error(request, '8 caracteres minimum.')
            else:
                messages.error(request, 'Les mots de passe ne correspondent pas.')
        
        user.save()
        return redirect('user_profile')
    
    return render(request, 'inventory/user_profile.html')


# ========== PRODUCT MANAGEMENT ==========
@staff_or_superuser_required
@login_required
def produit_list(request):
    produits = Produit.objects.all().order_by('designation')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        produits = produits.filter(
            Q(code_p__icontains=search_query) |
            Q(designation__icontains=search_query)
        )
    return render(request, 'inventory/produit_list.html', {'produits': produits, 'search_query': search_query})


@user_passes_test(lambda u: u.is_superuser)
def app_home(request):
    return render(request, 'inventory/app.html')


@user_passes_test(lambda u: u.is_superuser)
def produit_create(request):
    if request.method == 'POST':
        form = ProduitForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('produit_list')
    else:
        form = ProduitForm()
    return render(request, 'inventory/produit_form.html', {'form': form, 'title': 'Ajouter un produit'})


@user_passes_test(lambda u: u.is_superuser)
def produit_edit(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    if request.method == 'POST':
        form = ProduitForm(request.POST, instance=produit)
        if form.is_valid():
            form.save()
            return redirect('produit_list')
    else:
        form = ProduitForm(instance=produit)
    return render(request, 'inventory/produit_form.html', {'form': form, 'title': 'Modifier le produit'})


@user_passes_test(lambda u: u.is_superuser)
def produit_delete(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    if request.method == 'POST':
        try:
            produit.delete()
            messages.success(request, f"Produit '{produit.designation}' supprime.")
        except ProtectedError:
            messages.error(request, f"Impossible de supprimer '{produit.designation}'")
        return redirect('produit_list')
    return render(request, 'inventory/produit_confirm_delete.html', {'produit': produit})


@user_passes_test(lambda u: u.is_superuser)
def produit_history(request, pk):
    produit = get_object_or_404(Produit, pk=pk)
    entrees = LigneEntree.objects.filter(produit=produit).select_related('bon', 'bon__fournisseur', 'bon__utilisateur')
    sorties = LigneSortie.objects.filter(produit=produit).select_related('bon', 'bon__client', 'bon__utilisateur')
    
    history = []
    for ligne in entrees:
        history.append({
            'type': 'Entree',
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
@login_required
def product_list_api(request):
    produits = Produit.objects.all().values('code_p', 'designation', 'qte_stock', 'stock_alerte')
    return JsonResponse({'produits': list(produits)})


@csrf_exempt
@login_required
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
    
    produit = Produit.objects.create(
        designation=data.get('designation'),
        qte_stock=data.get('qte_stock', 0),
        stock_alerte=data.get('stock_alerte', 5)
    )
    return JsonResponse({
        'code_p': produit.code_p,
        'designation': produit.designation,
        'qte_stock': produit.qte_stock,
        'stock_alerte': produit.stock_alerte
    }, status=201)


@csrf_exempt
@login_required
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
    
    produit.designation = data.get('designation', produit.designation)
    produit.qte_stock = data.get('qte_stock', produit.qte_stock)
    produit.stock_alerte = data.get('stock_alerte', produit.stock_alerte)
    produit.save()
    
    return JsonResponse({
        'code_p': produit.code_p,
        'designation': produit.designation,
        'qte_stock': produit.qte_stock,
        'stock_alerte': produit.stock_alerte
    })


# ========== NOTIFICATIONS ==========
@login_required
@staff_or_superuser_required
@csrf_exempt
@require_POST
def notification_mark_read(request, product_id):
    try:
        produit = Produit.objects.get(pk=product_id)
    except Produit.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    
    utilisateur = get_user_profile(request.user)
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
    try:
        produit = Produit.objects.get(pk=product_id)
    except Produit.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    
    utilisateur = get_user_profile(request.user)
    status_obj, created = NotificationStatus.objects.get_or_create(
        utilisateur=utilisateur,
        produit=produit,
        defaults={'deleted': True}
    )
    if not created:
        status_obj.deleted = True
        status_obj.save()
    
    return JsonResponse({'status': 'ok'})


# ========== CLIENT MANAGEMENT ==========
@user_passes_test(lambda u: u.is_superuser)
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


@user_passes_test(lambda u: u.is_superuser)
def client_create(request):
    if request.method == 'POST':
        designation = request.POST.get('designation', '').strip()
        tel = request.POST.get('tel', '').strip()
        if designation:
            Client.objects.create(designation=designation, tel=tel)
            return redirect('client_list')
        return render(request, 'inventory/client_form.html', {'error': 'Nom requis'})
    return render(request, 'inventory/client_form.html')


@user_passes_test(lambda u: u.is_superuser)
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        client.designation = request.POST.get('designation', '').strip()
        client.tel = request.POST.get('tel', '').strip()
        if client.designation:
            client.save()
            return redirect('client_list')
        return render(request, 'inventory/client_form.html', {'client': client, 'error': 'Nom requis'})
    return render(request, 'inventory/client_form.html', {'client': client})


@user_passes_test(lambda u: u.is_superuser)
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        client.delete()
        messages.success(request, f"Client '{client.designation}' supprime")
        return redirect('client_list')
    return render(request, 'inventory/client_confirm_delete.html', {'client': client})


@user_passes_test(lambda u: u.is_superuser)
def client_history(request, pk):
    client = get_object_or_404(Client, pk=pk)
    bons = BonSortie.objects.filter(client=client).prefetch_related('lignes__produit').order_by('-date_s')
    return render(request, 'inventory/history_client.html', {'client': client, 'bons': bons})


# ========== FOURNISSEUR MANAGEMENT ==========
@user_passes_test(lambda u: u.is_superuser)
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


@user_passes_test(lambda u: u.is_superuser)
def fournisseur_create(request):
    if request.method == 'POST':
        designation = request.POST.get('designation', '').strip()
        tel = request.POST.get('tel', '').strip()
        if designation:
            Fournisseur.objects.create(designation=designation, tel=tel)
            return redirect('fournisseur_list')
        return render(request, 'inventory/fournisseur_form.html', {'error': 'Nom requis'})
    return render(request, 'inventory/fournisseur_form.html')


@user_passes_test(lambda u: u.is_superuser)
def fournisseur_edit(request, pk):
    fournisseur = get_object_or_404(Fournisseur, pk=pk)
    if request.method == 'POST':
        fournisseur.designation = request.POST.get('designation', '').strip()
        fournisseur.tel = request.POST.get('tel', '').strip()
        if fournisseur.designation:
            fournisseur.save()
            return redirect('fournisseur_list')
        return render(request, 'inventory/fournisseur_form.html', {'fournisseur': fournisseur, 'error': 'Nom requis'})
    return render(request, 'inventory/fournisseur_form.html', {'fournisseur': fournisseur})


@user_passes_test(lambda u: u.is_superuser)
def fournisseur_delete(request, pk):
    fournisseur = get_object_or_404(Fournisseur, pk=pk)
    if request.method == 'POST':
        fournisseur.delete()
        messages.success(request, f"Fournisseur '{fournisseur.designation}' supprime")
        return redirect('fournisseur_list')
    return render(request, 'inventory/fournisseur_confirm_delete.html', {'fournisseur': fournisseur})


@user_passes_test(lambda u: u.is_superuser)
def fournisseur_history(request, pk):
    fournisseur = get_object_or_404(Fournisseur, pk=pk)
    bons = BonEntree.objects.filter(fournisseur=fournisseur).prefetch_related('lignes__produit').order_by('-date_e')
    return render(request, 'inventory/history_fournisseur.html', {'fournisseur': fournisseur, 'bons': bons})


# ========== USER MANAGEMENT ==========
@user_passes_test(lambda u: u.is_superuser)
def user_list(request):
    users = User.objects.all().order_by('username')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    return render(request, 'inventory/user_list.html', {'users': users, 'search_query': search_query})


@user_passes_test(lambda u: u.is_superuser)
def user_create(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        role = request.POST.get('role', 'user')
        tel = request.POST.get('tel', '')
        is_staff = request.POST.get('is_staff') == 'on'
        is_superuser = request.POST.get('is_superuser') == 'on'
        
        if User.objects.filter(username=username).exists():
            messages.error(request, f"Nom d'utilisateur '{username}' deja pris")
            return redirect('user_create')
        
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name
        )
        
        user.is_staff = is_staff or is_superuser
        user.is_superuser = is_superuser
        user.save()
        
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
                'role': role,
                'tel': tel,
                'is_banned': False,
                'failed_login_attempts': 0
            }
        )
        
        from .utils import send_welcome_email, notify_admin_new_user
        send_welcome_email(user, temp_password)
        notify_admin_new_user(user, temp_password)
        
        request.session['new_user_id'] = user.id
        request.session['new_user_temp_password'] = temp_password
        
        messages.success(request, f"Utilisateur '{username}' cree avec succes")
        return redirect('user_created_info')
    
    return render(request, 'inventory/user_form.html', {'title': 'Ajouter un utilisateur'})


@user_passes_test(lambda u: u.is_superuser)
def admin_create_user(request):
    if request.method == 'POST':
        form = AdminUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
            user.set_password(temp_password)
            user.save()
            
            get_user_profile(user)
            send_welcome_email(user, temp_password)
            
            messages.success(request, f"Utilisateur '{user.username}' cree")
            return redirect('user_list')
    else:
        form = AdminUserCreationForm()
    return render(request, 'inventory/admin_create_user.html', {'form': form})


def user_created_info(request):
    user_id = request.session.get('new_user_id')
    temp_password = request.session.get('new_user_temp_password')
    
    if not user_id or not temp_password:
        return redirect('user_list')
    
    user = get_object_or_404(User, pk=user_id)
    
    for key in ['new_user_id', 'new_user_temp_password']:
        if key in request.session:
            del request.session[key]
    
    return render(request, 'inventory/user_created_info.html', {
        'user': user,
        'temp_password': temp_password,
        'now': timezone.now()
    })


@user_passes_test(lambda u: u.is_superuser)
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    profil = get_user_profile(user)
    
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
        
        messages.success(request, f"Utilisateur '{user.username}' mis a jour")
        return redirect('user_list')
    
    return render(request, 'inventory/user_form.html', {
        'form': AdminUserCreationForm(instance=user),
        'title': f"Modifier {user.username}",
        'edit_user': user,
        'profil': profil
    })


@user_passes_test(lambda u: u.is_superuser)
def user_edit_secure(request, pk):
    user = get_object_or_404(User, pk=pk)
    profil = get_user_profile(user)
    
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
        
        messages.success(request, f"Utilisateur '{user.username}' mis a jour")
        return redirect('user_list')
    
    return render(request, 'inventory/user_edit_secure.html', {'user': user, 'profil': profil})


@user_passes_test(lambda u: u.is_superuser)
def delete_user(request, pk):
    user = get_object_or_404(User, pk=pk)
    
    if user == request.user:
        messages.error(request, "Vous ne pouvez pas supprimer votre propre compte")
        return redirect('user_list')
    
    if user.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
        messages.error(request, "Impossible de supprimer le dernier administrateur")
        return redirect('user_list')
    
    if request.method == 'POST':
        username = user.username
        if hasattr(user, 'profil'):
            user.profil.delete()
        user.delete()
        messages.success(request, f"Utilisateur '{username}' supprime")
        return redirect('user_list')
    
    return render(request, 'inventory/user_confirm_delete.html', {'user_obj': user})


@user_passes_test(lambda u: u.is_superuser)
def toggle_user_ban(request, user_id):
    """Activer ou désactiver le bannissement d'un utilisateur"""
    profil = get_object_or_404(Utilisateur, id=user_id)
    
    # ✅ تحديث الحالة قبل العرض
    profil.update_ban_status()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        duration = request.POST.get('duration')
        
        if action == 'ban':
            profil.is_banned = True
            if duration and duration.isdigit():
                profil.ban_until = timezone.now() + timezone.timedelta(minutes=int(duration))
                message = f"✅ Utilisateur '{profil.user.username}' banni jusqu'au {profil.ban_until.strftime('%d/%m/%Y %H:%M')}"
            else:
                profil.ban_until = None
                message = f"✅ Utilisateur '{profil.user.username}' banni définitivement"
            profil.save()
            messages.success(request, message)
            
        elif action == 'unban':
            profil.is_banned = False
            profil.ban_until = None
            profil.failed_login_attempts = 0
            profil.save()
            messages.success(request, f"✅ Utilisateur '{profil.user.username}' a été débanni.")
        
        return redirect('user_list')
    
    return render(request, 'inventory/toggle_user_ban.html', {'profil': profil})

@user_passes_test(lambda u: u.is_superuser)
def user_history(request, username):
    user_obj = get_object_or_404(User, username=username)
    profil = get_user_profile(user_obj)
    
    entrees = BonEntree.objects.filter(utilisateur=profil).order_by('-date_e')
    sorties = BonSortie.objects.filter(utilisateur=profil).order_by('-date_s')
    return render(request, 'inventory/history_user.html', {'user_obj': user_obj, 'entrees': entrees, 'sorties': sorties})


# ========== BON ENTRÉE ==========
@staff_or_superuser_required
@login_required
def bon_entree_list(request):
    if request.user.is_superuser:
        bons = BonEntree.objects.all().order_by('-date_e')
    else:
        bons = BonEntree.objects.filter(utilisateur=get_user_profile(request.user)).order_by('-date_e')
    
    search_query = request.GET.get('q', '').strip()
    if search_query:
        bons = bons.filter(
            Q(num_e__icontains=search_query) |
            Q(fournisseur__designation__icontains=search_query) |
            Q(utilisateur__user__username__icontains=search_query)
        )
    return render(request, 'inventory/bon_entree_list.html', {'bons': bons, 'search_query': search_query})


@staff_or_superuser_required
@login_required
def bon_entree_create(request):
    fournisseurs = Fournisseur.objects.all()
    produits = Produit.objects.all()
    
    if request.method == 'POST':
        fournisseur_id = request.POST.get('fournisseur')
        produits_ids = request.POST.getlist('produit[]')
        qtes = request.POST.getlist('qte[]')
        
        if not fournisseur_id:
            messages.error(request, 'Selectionnez un fournisseur')
            return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
        
        fournisseur = Fournisseur.objects.filter(pk=fournisseur_id).first()
        if not fournisseur:
            messages.error(request, 'Fournisseur introuvable')
            return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
        
        utilisateur_obj = get_user_profile(request.user)
        lignes_data = []
        
        for i in range(len(produits_ids)):
            prod_id = produits_ids[i]
            qte_str = qtes[i]
            if not prod_id or not qte_str:
                continue
            
            try:
                qte = int(qte_str)
            except ValueError:
                messages.error(request, f"Quantite invalide ligne {i+1}")
                return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
            
            if qte <= 0:
                messages.error(request, f"Quantite doit etre > 0 ligne {i+1}")
                return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
            
            produit = Produit.objects.filter(pk=prod_id).first()
            if not produit:
                messages.error(request, f"Produit introuvable ligne {i+1}")
                return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
            
            lignes_data.append((produit, qte))
        
        if not lignes_data:
            messages.error(request, 'Aucune ligne valide')
            return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
        
        bon = BonEntree.objects.create(fournisseur=fournisseur, utilisateur=utilisateur_obj, date_e=timezone.now())
        
        for produit, qte in lignes_data:
            LigneEntree.objects.create(bon=bon, produit=produit, qte_e=qte)
            produit.qte_stock += qte
            produit.save()
        
        messages.success(request, f"Bon d'entree #{bon.num_e} cree")
        return redirect('bon_entree_list')
    
    return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})


@login_required
def bon_entree_detail(request, pk):
    bon = get_object_or_404(BonEntree, pk=pk)
    if not request.user.is_superuser and bon.utilisateur.user != request.user:
        return HttpResponseForbidden("Acces interdit")
    return render(request, 'inventory/bon_entree_detail.html', {'bon': bon, 'lignes': bon.lignes.all()})


@login_required
def bon_entree_delete(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Seuls les administrateurs peuvent supprimer")
    bon = get_object_or_404(BonEntree, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            for ligne in bon.lignes.all():
                ligne.produit.qte_stock -= ligne.qte_e
                ligne.produit.save()
            bon.delete()
        messages.success(request, f"Bon d'entree #{pk} supprime")
        return redirect('bon_entree_list')
    return render(request, 'inventory/bon_entree_confirm_delete.html', {'bon': bon})


# ========== BON SORTIE ==========
@staff_or_superuser_required
@login_required
def bon_sortie_list(request):
    if request.user.is_superuser:
        bons = BonSortie.objects.all().order_by('-date_s')
    else:
        bons = BonSortie.objects.filter(utilisateur=get_user_profile(request.user)).order_by('-date_s')
    
    search_query = request.GET.get('q', '').strip()
    if search_query:
        bons = bons.filter(
            Q(num_s__icontains=search_query) |
            Q(client__designation__icontains=search_query) |
            Q(utilisateur__user__username__icontains=search_query)
        )
    return render(request, 'inventory/bon_sortie_list.html', {'bons': bons, 'search_query': search_query})


@staff_or_superuser_required
@login_required
def bon_sortie_create(request):
    clients = Client.objects.all()
    produits = Produit.objects.all()
    
    if request.method == 'POST':
        client_id = request.POST.get('client')
        produits_ids = request.POST.getlist('produit[]')
        qtes = request.POST.getlist('qte[]')
        
        if not client_id:
            messages.error(request, 'Selectionnez un client')
            return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
        
        client = Client.objects.filter(pk=client_id).first()
        if not client:
            messages.error(request, 'Client introuvable')
            return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
        
        utilisateur_obj = get_user_profile(request.user)
        lignes_data = []
        
        for i in range(len(produits_ids)):
            prod_id = produits_ids[i]
            qte_str = qtes[i]
            if not prod_id or not qte_str:
                continue
            
            try:
                qte = int(qte_str)
            except ValueError:
                messages.error(request, f"Quantite invalide ligne {i+1}")
                return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
            
            if qte <= 0:
                messages.error(request, f"Quantite doit etre > 0 ligne {i+1}")
                return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
            
            produit = Produit.objects.filter(pk=prod_id).first()
            if not produit:
                messages.error(request, f"Produit introuvable ligne {i+1}")
                return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
            
            if qte > produit.qte_stock:
                messages.error(request, f"Stock insuffisant pour '{produit.designation}'. Disponible: {produit.qte_stock}")
                return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
            
            lignes_data.append((produit, qte))
        
        if not lignes_data:
            messages.error(request, 'Aucune ligne valide')
            return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
        
        bon = BonSortie.objects.create(client=client, utilisateur=utilisateur_obj, date_s=timezone.now())
        low_stock_products = []
        
        for produit, qte in lignes_data:
            LigneSortie.objects.create(bon=bon, produit=produit, qte_s=qte)
            produit.qte_stock -= qte
            produit.save()
            if produit.qte_stock <= produit.stock_alerte:
                low_stock_products.append(produit.designation)
        
        if low_stock_products:
            messages.warning(request, f"Stock faible : {', '.join(low_stock_products)}")
        
        messages.success(request, f"Bon de sortie #{bon.num_s} cree")
        return redirect('bon_sortie_detail', pk=bon.pk)
    
    return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})


@login_required
def bon_sortie_detail(request, pk):
    bon = get_object_or_404(BonSortie, pk=pk)
    if not request.user.is_superuser and bon.utilisateur.user != request.user:
        return HttpResponseForbidden("Acces interdit")
    return render(request, 'inventory/bon_sortie_detail.html', {'bon': bon, 'lignes': bon.lignes.all()})


@login_required
def bon_sortie_delete(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Seuls les administrateurs peuvent supprimer")
    bon = get_object_or_404(BonSortie, pk=pk)
    if request.method == 'POST':
        with transaction.atomic():
            for ligne in bon.lignes.all():
                ligne.produit.qte_stock += ligne.qte_s
                ligne.produit.save()
            bon.delete()
        messages.success(request, f"Bon de sortie #{pk} supprime")
        return redirect('bon_sortie_list')
    return render(request, 'inventory/bon_sortie_confirm_delete.html', {'bon': bon})


# ========== ADMIN OTP ==========
@login_required
@user_passes_test(lambda u: u.is_superuser)
def setup_admin_otp(request):
    profil = get_user_profile(request.user)
    
    if request.method == 'POST':
        if 'enable' in request.POST:
            secret = pyotp.random_base32()
            profil.otp_secret = secret
            profil.otp_enabled = True
            profil.save()
            
            totp = pyotp.TOTP(secret)
            otp_uri = totp.provisioning_uri(name=request.user.email, issuer_name="Gestion Stock")
            
            return render(request, 'inventory/admin_otp_setup.html', {'otp_uri': otp_uri, 'secret': secret})
        elif 'disable' in request.POST:
            profil.otp_enabled = False
            profil.otp_secret = None
            profil.save()
            messages.success(request, "OTP desactive")
            return redirect('home')
    
    return render(request, 'inventory/admin_otp_setup.html', {'otp_enabled': profil.otp_enabled})


@login_required
def admin_otp_verify(request):
    user_id = request.session.get('pre_otp_user_id')
    if not user_id:
        return redirect('login')
    
    user = get_object_or_404(User, pk=user_id)
    
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
                    messages.error(request, "Code OTP invalide")
    else:
        form = AdminOTPForm()
    
    return render(request, 'inventory/admin_otp_verify.html', {'form': form, 'user': user})


# ========== ADMIN REPORT ==========
@user_passes_test(lambda u: u.is_superuser)
def admin_report(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    entrees = BonEntree.objects.none()
    sorties = BonSortie.objects.none()
    stats = {'total_entrees': 0, 'total_sorties': 0}
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
                
                fournisseur_totals = LigneEntree.objects.filter(bon__in=entrees).values(
                    'bon__fournisseur__num_f', 'bon__fournisseur__designation'
                ).annotate(total_qte=Sum('qte_e')).order_by('-total_qte')[:5]
                
                for f in fournisseur_totals:
                    top_fournisseurs.append({
                        'num': f['bon__fournisseur__num_f'],
                        'name': f['bon__fournisseur__designation'],
                        'total_qte': f['total_qte'],
                    })
                
                client_totals = LigneSortie.objects.filter(bon__in=sorties).values(
                    'bon__client__code_cl', 'bon__client__designation'
                ).annotate(total_qte=Sum('qte_s')).order_by('-total_qte')[:5]
                
                for c in client_totals:
                    top_clients.append({
                        'code': c['bon__client__code_cl'],
                        'name': c['bon__client__designation'],
                        'total_qte': c['total_qte'],
                    })
            else:
                error = "Format de date invalide"
        except Exception as e:
            error = f"Erreur: {str(e)}"
    elif start_date or end_date:
        error = "Veuillez fournir les deux dates"
    
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
@user_passes_test(lambda u: u.is_superuser)
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


# ========== OTP PASSWORD CHANGE ==========
def request_password_change_otp(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        try:
            user = User.objects.get(username=username)
            profil = get_user_profile(user)
            
            if not profil.otp_secret:
                profil.otp_secret = pyotp.random_base32()
                profil.save()
            
            totp = pyotp.TOTP(profil.otp_secret)
            otp_code = totp.now()
            
            request.session['reset_otp'] = otp_code
            request.session['reset_user_id'] = user.id
            request.session['reset_otp_expires'] = (timezone.now() + timezone.timedelta(minutes=5)).timestamp()
            
            from .utils import send_otp_email
            send_otp_email(user, otp_code, "reinitialiser votre mot de passe")
            
            messages.success(request, "Un code OTP a ete envoye a votre email")
            return redirect('change_password_with_otp')
        except User.DoesNotExist:
            messages.error(request, "Utilisateur non trouve")
    
    return render(request, 'inventory/request_otp.html')


def change_password_with_otp(request):
    user_id = request.session.get('reset_user_id')
    
    if not user_id:
        return redirect('request_password_change_otp')
    
    user = get_object_or_404(User, pk=user_id)
    stored_otp = request.session.get('reset_otp')
    expires = request.session.get('reset_otp_expires', 0)
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "Code OTP expire")
        return redirect('request_password_change_otp')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if otp_code != stored_otp:
            messages.error(request, "Code OTP invalide")
            return render(request, 'inventory/change_password.html', {'require_otp': True})
        
        if new_password != confirm_password:
            messages.error(request, "Les mots de passe ne correspondent pas")
            return render(request, 'inventory/change_password.html', {'require_otp': False})
        
        if len(new_password) < 8:
            messages.error(request, "8 caracteres minimum")
            return render(request, 'inventory/change_password.html', {'require_otp': False})
        
        user.set_password(new_password)
        user.save()
        
        if hasattr(user, 'profil'):
            user.profil.must_change_password = False
            user.profil.save()
        
        for key in ['reset_user_id', 'reset_otp', 'reset_otp_expires']:
            if key in request.session:
                del request.session[key]
        
        messages.success(request, "Mot de passe change avec succes")
        return redirect('login')
    
    return render(request, 'inventory/change_password.html', {'require_otp': True})


# ========== CHANGE PASSWORD WITH OTP ==========
@login_required

@login_required
def change_password_request(request):
    """الخطوة 1: طلب تغيير كلمة السر مع التحقق من القديمة"""
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if not request.user.check_password(old_password):
            messages.error(request, "Mot de passe actuel incorrect")
            return redirect('change_password_request')
        
        if new_password != confirm_password:
            messages.error(request, "Les mots de passe ne correspondent pas")
            return redirect('change_password_request')
        
        if len(new_password) < 8:
            messages.error(request, "Le mot de passe doit contenir au moins 8 caractères")
            return redirect('change_password_request')
        
        # ✅ تخزين كلمة السر الجديدة في cache
        cache_key = f"pending_pw_{request.user.id}"
        cache.set(cache_key, new_password, 300)  # تخزين لمدة 5 دقائق
        
        request.session['pending_cache_key'] = cache_key
        
        return redirect('request_otp_for_password_change')
    
    return render(request, 'inventory/change_password_request.html')




@login_required
def change_password_otp_verify(request):
    """التحقق من OTP وتغيير كلمة السر"""
    stored_otp = request.session.get('change_pw_otp')
    expires = request.session.get('change_pw_otp_expires', 0)
    
    # ✅ جلب كلمة السر من cache
    cache_key = request.session.get('pending_cache_key')
    pending_password = cache.get(cache_key) if cache_key else None
    
    # ✅ التحقق من وجود البيانات
    if not stored_otp:
        messages.error(request, "Session expirée, veuillez recommencer")
        return redirect('change_password_request')
    
    if not pending_password:
        messages.error(request, "Session expirée, veuillez recommencer")
        return redirect('change_password_request')
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "Code OTP expiré, veuillez recommencer")
        return redirect('change_password_request')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if otp_code != stored_otp:
            messages.error(request, "Code OTP invalide")
            return redirect('change_password_otp_verify')
        
        # OTP correct, changer le mot de passe
        user = request.user
        user.set_password(pending_password)
        user.save()
        
        if hasattr(user, 'profil'):
            user.profil.must_change_password = False
            user.profil.password_changed_at = timezone.now()
            user.profil.save()
        
        # ✅ Nettoyer cache et session
        if cache_key:
            cache.delete(cache_key)
        
        session_keys = ['change_pw_otp', 'change_pw_otp_expires', 'pending_cache_key']
        for key in session_keys:
            if key in request.session:
                del request.session[key]
        
        update_session_auth_hash(request, user)
        
        from .utils import notify_admin_password_change
        notify_admin_password_change(user)
        
        messages.success(request, "Votre mot de passe a été changé avec succès")
        return redirect('user_profile')
    
    return render(request, 'inventory/change_password_otp_verify.html')

# ========== RESET PASSWORD VIA EMAIL (Forgot) ==========
def reset_password_request(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email)
            if hasattr(user, 'profil'):
                profil = user.profil
                
                token = secrets.token_urlsafe(32)
                profil.reset_password_token = token
                profil.reset_token_expires = timezone.now() + timezone.timedelta(hours=24)
                profil.save()
                
                reset_link = request.build_absolute_uri(reverse('reset_password_with_otp', args=[token]))
                
                from .utils import send_email_to_user
                send_email_to_user(user, 
                    'Reinitialisation de votre mot de passe',
                    f'Bonjour {user.username},\n\nCliquez sur le lien suivant pour reinitialiser votre mot de passe:\n{reset_link}\n\nCe lien expire dans 24 heures.'
                )
                
                messages.success(request, "Un email de reinitialisation a ete envoye")
                return redirect('login')
        except User.DoesNotExist:
            pass
        messages.success(request, "Si cet email existe, un lien de reinitialisation a ete envoye")
        return redirect('login')
    
    return render(request, 'inventory/reset_password_request.html')


def reset_password_with_otp(request, token):
    try:
        profil = Utilisateur.objects.get(reset_password_token=token, reset_token_expires__gt=timezone.now())
        user = profil.user
    except Utilisateur.DoesNotExist:
        messages.error(request, "Lien invalide ou expire")
        return redirect('login')
    
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if new_password != confirm_password:
            messages.error(request, "Les mots de passe ne correspondent pas")
            return render(request, 'inventory/reset_password_with_otp.html', {'token': token})
        
        if len(new_password) < 8:
            messages.error(request, "8 caracteres minimum")
            return render(request, 'inventory/reset_password_with_otp.html', {'token': token})
        
        request.session['reset_new_password'] = new_password
        request.session['reset_user_id'] = user.id
        request.session['reset_token'] = token
        
        if not profil.otp_secret:
            profil.otp_secret = pyotp.random_base32()
            profil.save()
        
        totp = pyotp.TOTP(profil.otp_secret)
        otp_code = totp.now()
        
        request.session['reset_otp'] = otp_code
        request.session['reset_otp_expires'] = (timezone.now() + timezone.timedelta(minutes=5)).timestamp()
        
        from .utils import send_otp_email
        send_otp_email(user, otp_code, "reinitialiser votre mot de passe")
        
        return redirect('reset_password_otp_verify')
    
    return render(request, 'inventory/reset_password_with_otp.html', {'token': token})


def reset_password_otp_verify(request):
    user_id = request.session.get('reset_user_id')
    new_password = request.session.get('reset_new_password')
    stored_otp = request.session.get('reset_otp')
    expires = request.session.get('reset_otp_expires', 0)
    token = request.session.get('reset_token')
    
    if not user_id or not new_password or not stored_otp:
        messages.error(request, "Session expiree")
        return redirect('login')
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "Code OTP expire")
        return redirect('login')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if otp_code != stored_otp:
            messages.error(request, "Code OTP invalide")
            return render(request, 'inventory/reset_password_otp_verify.html')
        
        user = get_object_or_404(User, pk=user_id)
        user.set_password(new_password)
        user.save()
        
        if hasattr(user, 'profil'):
            user.profil.reset_password_token = None
            user.profil.reset_token_expires = None
            user.profil.must_change_password = False
            user.profil.save()
        
        for key in ['reset_user_id', 'reset_new_password', 'reset_otp', 'reset_otp_expires', 'reset_token']:
            if key in request.session:
                del request.session[key]
        
        messages.success(request, "Votre mot de passe a ete reinitialise avec succes")
        return redirect('login')
    
    return render(request, 'inventory/reset_password_otp_verify.html')


# ========== GENERATE PDF REPORT ==========
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
import io

def generate_pdf_report(request):
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    entrees = BonEntree.objects.none()
    sorties = BonSortie.objects.none()
    stats = {'total_entrees': 0, 'total_sorties': 0}
    top_products = []
    top_fournisseurs = []
    top_clients = []
    
    if start_date and end_date:
        start = parse_date(start_date)
        end = parse_date(end_date)
        if start and end:
            entrees = BonEntree.objects.filter(date_e__date__gte=start, date_e__date__lte=end).order_by('-date_e')
            sorties = BonSortie.objects.filter(date_s__date__gte=start, date_s__date__lte=end).order_by('-date_s')
            
            stats['total_entrees'] = entrees.count()
            stats['total_sorties'] = sorties.count()
            
            product_entries = LigneEntree.objects.filter(bon__in=entrees).values('produit__code_p', 'produit__designation').annotate(total_in=Sum('qte_e'))
            product_exits = LigneSortie.objects.filter(bon__in=sorties).values('produit__code_p', 'produit__designation').annotate(total_out=Sum('qte_s'))
            
            product_totals = {}
            for p in product_entries:
                product_totals[p['produit__code_p']] = {
                    'designation': p['produit__designation'],
                    'total_in': p['total_in'] or 0,
                    'total_out': 0,
                }
            for p in product_exits:
                code = p['produit__code_p']
                if code in product_totals:
                    product_totals[code]['total_out'] = p['total_out'] or 0
                else:
                    product_totals[code] = {
                        'designation': p['produit__designation'],
                        'total_in': 0,
                        'total_out': p['total_out'] or 0,
                    }
            for code, data in product_totals.items():
                data['total_moved'] = data['total_in'] + data['total_out']
            top_products = sorted(product_totals.values(), key=lambda x: x['total_out'], reverse=True)[:10]
            
            fournisseur_totals = LigneEntree.objects.filter(bon__in=entrees).values(
                'bon__fournisseur__num_f', 'bon__fournisseur__designation'
            ).annotate(total_qte=Sum('qte_e')).order_by('-total_qte')[:10]
            
            for f in fournisseur_totals:
                top_fournisseurs.append({
                    'num': f['bon__fournisseur__num_f'],
                    'name': f['bon__fournisseur__designation'],
                    'total_qte': f['total_qte'] or 0,
                })
            
            client_totals = LigneSortie.objects.filter(bon__in=sorties).values(
                'bon__client__code_cl', 'bon__client__designation'
            ).annotate(total_qte=Sum('qte_s')).order_by('-total_qte')[:10]
            
            for c in client_totals:
                top_clients.append({
                    'code': c['bon__client__code_cl'],
                    'name': c['bon__client__designation'],
                    'total_qte': c['total_qte'] or 0,
                })
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'entrees': entrees,
        'sorties': sorties,
        'stats': stats,
        'top_products': top_products,
        'top_fournisseurs': top_fournisseurs,
        'top_clients': top_clients,
        'now': timezone.now(),
        'user': request.user,
    }
    
    template = get_template('inventory/report_pdf.html')
    html = template.render(context)
    
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)
    
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        filename = f"rapport_{start_date}_{end_date}.pdf" if start_date and end_date else "rapport.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    
    return HttpResponse("Erreur lors de la generation du PDF", status=500)

def request_otp_for_password_change(request):
    """طلب OTP لتغيير كلمة السر بعد تسجيل الدخول"""
    if not request.user.is_authenticated:
        return redirect('login')
    
    # التحقق من وجود كلمة السر في cache
    cache_key = request.session.get('pending_cache_key')
    pending_password = cache.get(cache_key) if cache_key else None
    
    if not pending_password:
        messages.error(request, "Session expirée, veuillez recommencer")
        return redirect('change_password_request')
    
    # ✅ معالجة POST (إرسال OTP)
    if request.method == 'POST':
        user = request.user
        profil = get_user_profile(user)
        
        if not profil.otp_secret:
            profil.otp_secret = pyotp.random_base32()
            profil.save()
        
        totp = pyotp.TOTP(profil.otp_secret)
        otp_code = totp.now()
        
        request.session['change_pw_otp'] = otp_code
        request.session['change_pw_otp_expires'] = (timezone.now() + timezone.timedelta(minutes=5)).timestamp()
        
        from .utils import send_otp_email
        send_otp_email(user, otp_code, "changer votre mot de passe")
        
        # ✅ دائماً نعيد التوجيه إلى صفحة التحقق من OTP
        messages.success(request, "Un code OTP a été envoyé à votre email")
        return redirect('change_password_otp_verify')
    
    # ✅ GET request - عرض الصفحة
    return render(request, 'inventory/request_otp_pw_change.html')

@login_required
def request_email_change(request):
    user = request.user
    
    if user.is_superuser:
        messages.error(request, "Vous êtes administrateur, utilisez le formulaire normal.")
        return redirect('user_profile')
    
    if request.method == 'POST':
        new_email = request.POST.get('new_email')
        
        if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
            messages.error(request, "Cet email est déjà utilisé par un autre compte.")
            return redirect('user_profile')
        
        # Générer un token unique
        import secrets
        token = secrets.token_urlsafe(32)
        
        profil = get_user_profile(user)
        profil.email_change_requested = new_email
        profil.email_change_token = token
        profil.email_change_request_date = timezone.now()
        profil.save()
        
        # ✅ Envoyer une notification à TOUS les admins
        admins = User.objects.filter(is_superuser=True)
        for admin in admins:
            if hasattr(admin, 'profil'):
                Notification.objects.create(
                    recipient=admin.profil,
                    type='email_request',
                    title='Demande de changement d\'email',
                    message=f"L'utilisateur '{user.username}' demande de changer son email de '{user.email}' vers '{new_email}'.",
                    link=reverse('approve_email_change', args=[token]),
                )
        
        messages.success(request, "Votre demande a été envoyée. Vous recevrez une notification une fois traitée.")
        return redirect('user_profile')
    
    return render(request, 'inventory/request_email_change.html')

@user_passes_test(lambda u: u.is_superuser)
def approve_email_change(request, token):
    """L'admin approuve la demande de changement d'email"""
    try:
        profil = Utilisateur.objects.get(email_change_token=token, email_change_requested__isnull=False)
    except Utilisateur.DoesNotExist:
        messages.error(request, "Lien invalide ou expiré.")
        return redirect('user_list')
    
    user = profil.user
    new_email = profil.email_change_requested
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve':
            # ✅ Vérifier que l'email n'est pas déjà utilisé
            if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
                messages.error(request, f"L'email '{new_email}' est déjà utilisé par un autre compte.")
                return redirect('user_list')
            
            # ✅ Générer un token pour l'utilisateur
            import secrets
            confirm_token = secrets.token_urlsafe(32)
            
            # ✅ Stocker le nouvel email dans pending
            profil.pending_email_new = new_email
            profil.email_change_token = confirm_token
            profil.save()
            
            # ✅ Envoyer un email de confirmation à l'utilisateur avec lien
            from .utils import send_email_to_user
            confirm_link = request.build_absolute_uri(reverse('confirm_email_with_password', args=[confirm_token]))
            
            send_email_to_user(
                user,
                "Demande de changement d'email approuvée",
                f"Bonjour {user.username},\n\n"
                f"L'administrateur a approuvé votre demande de changement d'email vers '{new_email}'.\n\n"
                f"Cliquez sur le lien suivant pour confirmer avec votre mot de passe :\n{confirm_link}\n\n"
                f"Ce lien expire dans 24 heures.\n\n"
                f"Si vous n'avez pas demandé ce changement, ignorez cet email."
            )
            
            # ✅ Notification pour l'utilisateur
            Notification.objects.create(
                recipient=profil,
                type='email_approved',
                title='Demande approuvée',
                message=f"Votre demande de changement d'email vers '{new_email}' a été approuvée. Cliquez pour confirmer avec votre mot de passe.",
                link=reverse('confirm_email_with_password', args=[confirm_token]),
            )
            
            messages.success(request, f"Demande de '{user.username}' approuvée. Un email a été envoyé à l'utilisateur pour finaliser le changement.")
            
        elif action == 'reject':
            # ❌ Refuser la demande
            profil.email_change_requested = None
            profil.email_change_token = None
            profil.email_change_request_date = None
            profil.save()
            
            # Notification de refus
            Notification.objects.create(
                recipient=profil,
                type='email_rejected',
                title='Demande refusée',
                message=f"Votre demande de changement d'email vers '{new_email}' a été refusée.",
                link=reverse('user_profile'),
            )
            
            messages.info(request, f"Demande de changement d'email de '{user.username}' refusée.")
        
        return redirect('user_list')
    
    return render(request, 'inventory/approve_email_change.html', {
        'user': user,
        'new_email': new_email,
        'token': token
    })

@login_required
def admin_secure_change(request):
    """L'admin doit confirmer avec OTP avant de modifier ses infos"""
    if not request.user.is_superuser:
        return redirect('home')
    
    user = request.user
    profil = get_user_profile(user)
    
    if request.method == 'POST':
        # Vérifier l'OTP
        otp_code = request.POST.get('otp_code')
        password = request.POST.get('password')
        
        if not user.check_password(password):
            messages.error(request, "Mot de passe incorrect.")
            return redirect('admin_secure_change')
        
        # Générer OTP
        import random
        otp = ''.join(random.choices('0123456789', k=6))
        
        profil.pending_admin_otp = otp
        profil.pending_admin_otp_expires = timezone.now() + timezone.timedelta(minutes=5)
        
        # Stocker les modifications en session
        request.session['pending_admin_changes'] = {
            'username': request.POST.get('username'),
            'email': request.POST.get('email'),
            'first_name': request.POST.get('first_name', ''),
            'last_name': request.POST.get('last_name', ''),
        }
        profil.save()
        
        # Envoyer OTP par email
        from .utils import send_otp_email
        send_otp_email(user, otp, "modifier vos informations personnelles")
        
        messages.info(request, "Un code OTP a été envoyé à votre email.")
        return redirect('admin_confirm_change')
    
    return render(request, 'inventory/admin_secure_change.html', {'user': user})


@login_required
def admin_confirm_change(request):
    """L'admin confirme les modifications avec OTP"""
    if not request.user.is_superuser:
        return redirect('home')
    
    profil = get_user_profile(request.user)
    pending_changes = request.session.get('pending_admin_changes', {})
    
    if not pending_changes:
        return redirect('admin_secure_change')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if (profil.pending_admin_otp == otp_code and 
            profil.pending_admin_otp_expires > timezone.now()):
            
            # Appliquer les modifications
            user = request.user
            user.username = pending_changes.get('username')
            user.email = pending_changes.get('email')
            user.first_name = pending_changes.get('first_name', '')
            user.last_name = pending_changes.get('last_name', '')
            user.save()
            
            # Nettoyer
            profil.pending_admin_otp = None
            profil.pending_admin_otp_expires = None
            profil.save()
            
            del request.session['pending_admin_changes']
            
            messages.success(request, "Vos informations ont été mises à jour.")
            return redirect('user_profile')
        else:
            messages.error(request, "Code OTP invalide ou expiré.")
    
    return render(request, 'inventory/admin_confirm_change.html')

def confirm_new_email(request, token):
    try:
        profil = Utilisateur.objects.get(email_change_token=token, email_change_requested__isnull=False)
    except Utilisateur.DoesNotExist:
        messages.error(request, "Lien invalide ou expiré.")
        return redirect('login')
    
    user = profil.user
    new_email = profil.email_change_requested
    
    if request.method == 'POST':
        # Changer l'email
        user.email = new_email
        user.save()
        
        # ✅ Envoyer notification de confirmation
        Notification.objects.create(
            recipient=profil,
            type='email_confirmed',
            title='Email confirmé',
            message=f"Votre email a été changé avec succès vers '{new_email}'.",
            link=reverse('user_profile'),
        )
        
        # Nettoyer
        profil.email_change_requested = None
        profil.email_change_token = None
        profil.email_change_request_date = None
        profil.save()
        
        messages.success(request, f"Votre email a été changé avec succès vers {new_email}")
        return redirect('user_profile')
    
    return render(request, 'inventory/confirm_new_email.html', {
        'user': user,
        'new_email': new_email,
        'token': token
    })

def confirm_email_with_password(request, token):
    """L'utilisateur confirme le changement d'email avec son mot de passe + OTP"""
    try:
        profil = Utilisateur.objects.get(email_change_token=token, pending_email_new__isnull=False)
    except Utilisateur.DoesNotExist:
        messages.error(request, "Lien invalide ou expiré.")
        return redirect('login')
    
    user = profil.user
    new_email = profil.pending_email_new
    
    # Étape 1: Vérifier le mot de passe
    if request.method == 'POST':
        step = request.POST.get('step')
        
        if step == 'password':
            password = request.POST.get('password')
            
            if not user.check_password(password):
                messages.error(request, "Mot de passe incorrect.")
                return render(request, 'inventory/confirm_email_step1.html', {
                    'new_email': new_email,
                    'token': token
                })
            
            # ✅ Mot de passe correct, générer OTP et l'envoyer au nouvel email
            import pyotp
            import random
            
            # Générer un secret OTP
            secret = pyotp.random_base32()
            totp = pyotp.TOTP(secret)
            otp_code = totp.now()
            
            # Stocker en base
            profil.pending_email_otp_secret = secret
            profil.pending_email_otp_code = otp_code
            profil.pending_email_otp_expires = timezone.now() + timezone.timedelta(minutes=10)
            profil.save()
            
            # Envoyer OTP au NOUVEL email
            from .utils import send_email_to_user
            # Créer un utilisateur temporaire pour envoyer l'email
            temp_user = User()
            temp_user.email = new_email
            temp_user.username = user.username
            
            send_email_to_user(
                temp_user,
                "Code de vérification pour votre nouvel email",
                f"Bonjour {user.username},\n\n"
                f"Votre code OTP pour confirmer votre nouvel email '{new_email}' est : {otp_code}\n\n"
                f"Ce code expire dans 10 minutes.\n\n"
                f"Si vous n'avez pas demandé ce changement, ignorez cet email."
            )
            
            return render(request, 'inventory/confirm_email_step2.html', {
                'new_email': new_email,
                'token': token
            })
        
        elif step == 'otp':
            otp_code = request.POST.get('otp_code')
            
            # Vérifier OTP
            if (profil.pending_email_otp_code == otp_code and 
                profil.pending_email_otp_expires > timezone.now()):
                
                # ✅ Tout est bon, changer l'email
                user.email = new_email
                user.save()
                
                # Nettoyer tous les champs
                profil.email_change_requested = None
                profil.email_change_token = None
                profil.email_change_request_date = None
                profil.pending_email_new = None
                profil.pending_email_otp_secret = None
                profil.pending_email_otp_code = None
                profil.pending_email_otp_expires = None
                profil.save()
                
                # Notification de confirmation
                Notification.objects.create(
                    recipient=profil,
                    type='email_confirmed',
                    title='Email changé avec succès',
                    message=f"Votre email a été changé vers '{new_email}'.",
                    link=reverse('user_profile'),
                )
                
                messages.success(request, f"Votre email a été changé avec succès vers {new_email}")
                return redirect('user_profile')
            else:
                messages.error(request, "Code OTP invalide ou expiré.")
    
    return render(request, 'inventory/confirm_email_step1.html', {
        'new_email': new_email,
        'token': token
    })

@login_required
def mark_notification_read(request, notification_id):
    """Marquer une notification comme lue"""
    try:
        notification = Notification.objects.get(id=notification_id, recipient=request.user.profil)
        notification.is_read = True
        notification.save()
        return JsonResponse({'status': 'ok'})
    except Notification.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Notification non trouvée'}, status=404)
    
@login_required
def mark_all_notifications_read(request):
    """Marquer toutes les notifications comme lues"""
    try:
        Notification.objects.filter(recipient=request.user.profil, is_read=False).update(is_read=True)
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

from .models import Notification, Produit, Utilisateur

def check_and_create_low_stock_notifications():
    """Vérifier les produits en stock faible et créer des notifications"""
    low_stock_products = Produit.objects.filter(qte_stock__lte=F('stock_alerte'))
    
    for produit in low_stock_products:
        # Vérifier si une notification existe déjà pour ce produit
        existing_notif = Notification.objects.filter(
            type='stock_alert',
            message__icontains=produit.designation
        ).first()
        
        if not existing_notif:
            # Créer une notification pour tous les utilisateurs (ou juste les admins)
            for utilisateur in Utilisateur.objects.all():
                Notification.objects.create(
                    recipient=utilisateur,
                    type='stock_alert',
                    title='⚠️ Stock faible',
                    message=f"Le produit '{produit.designation}' a un stock faible : {produit.qte_stock} unités.",
                    link='/produits/',
                    is_read=False
                )

@login_required
def mark_notification_read(request, notification_id):
    """Mark a system notification as read"""
    try:
        notification = Notification.objects.get(id=notification_id, recipient=request.user.profil)
        notification.is_read = True
        notification.save()
        return JsonResponse({'status': 'ok'})
    except Notification.DoesNotExist:
        return JsonResponse({'error': 'Notification not found'}, status=404)
    
@login_required
@csrf_exempt
@require_POST
def notification_mark_read(request, product_id):
    """Mark a low‑stock notification as read for the current user ONLY"""
    try:
        product_id = int(product_id)
        produit = Produit.objects.get(pk=product_id)
    except (Produit.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'error': 'Product not found'}, status=404)

    utilisateur = get_user_profile(request.user)
    
    # ✅ إنشاء أو تحديث الحالة للمستخدم الحالي فقط
    status_obj, created = NotificationStatus.objects.get_or_create(
        utilisateur=utilisateur,
        produit=produit,
        defaults={'read': True}
    )
    if not created:
        status_obj.read = True
        status_obj.save()

    return JsonResponse({'status': 'ok'})

@user_passes_test(lambda u: u.is_superuser)
@csrf_exempt
def update_all_ban_status(request):
    """Mettre à jour le statut de bannissement de tous les utilisateurs"""
    from .models import Utilisateur
    updated = 0
    for profil in Utilisateur.objects.filter(is_banned=True, ban_until__isnull=False):
        if profil.ban_until <= timezone.now():
            profil.is_banned = False
            profil.ban_until = None
            profil.failed_login_attempts = 0
            profil.save()
            updated += 1
    return JsonResponse({'status': 'ok', 'updated': updated})