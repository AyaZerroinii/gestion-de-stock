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
    """الحصول على ملف تعريف المستخدم أو إنشاؤه إذا لم يكن موجوداً"""
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
                is_locked, lock_message = user_obj.profil.is_account_locked()
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
            
            # Générer et envoyer OTP
            profil = get_user_profile(user)
            if not profil.otp_secret:
                profil.otp_secret = pyotp.random_base32()
                profil.save()
            
            totp = pyotp.TOTP(profil.otp_secret)
            otp_code = totp.now()
            
            request.session['login_otp'] = otp_code
            request.session['login_otp_expires'] = (timezone.now() + timezone.timedelta(minutes=5)).timestamp()
            
            # Envoyer OTP par email
            try:
                send_mail(
                    '🔐 Code de vérification OTP',
                    f'Bonjour {user.username},\n\nVotre code OTP pour vous connecter est : {otp_code}\n\nCe code expire dans 5 minutes.',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=True,
                )
            except:
                pass
            
            return redirect('verify_login_otp')
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


def verify_login_otp(request):
    """التحقق من OTP بعد تسجيل الدخول"""
    user_id = request.session.get('pre_otp_user_id')
    
    if not user_id:
        return redirect('login')
    
    user = get_object_or_404(User, pk=user_id)
    
    stored_otp = request.session.get('login_otp')
    expires = request.session.get('login_otp_expires', 0)
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "❌ Code OTP expiré")
        return redirect('login')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if otp_code == stored_otp:
            # OTP correct, on connecte l'utilisateur
            login(request, user)
            
            # Nettoyer la session
            for key in ['pre_otp_user_id', 'login_otp', 'login_otp_expires']:
                if key in request.session:
                    del request.session[key]
            
            # 🔐 جدد هذا الجزء ==========
            # Si l'utilisateur doit changer son mot de passe (première connexion)
            if hasattr(user, 'profil') and user.profil.must_change_password:
                messages.info(request, "🔐 Veuillez changer votre mot de passe temporaire")
                return redirect('request_otp_for_password_change')
            # ===========================
            
            return redirect('home')
        else:
            messages.error(request, "❌ Code OTP invalide")
    
    return render(request, 'inventory/verify_otp.html', {'username': user.username})


def custom_logout(request):
    logout(request)
    messages.success(request, "✅ Vous avez été déconnecté avec succès.")
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
            
            messages.success(request, "✅ Votre mot de passe a été changé avec succès.")
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
                            'Réinitialisation de votre mot de passe',
                            f'Bonjour {user.username},\n\nCliquez sur le lien suivant :\n{reset_link}\n\nCe lien expire dans 24 heures.',
                            settings.DEFAULT_FROM_EMAIL,
                            [email],
                            fail_silently=True,
                        )
                    except:
                        pass
                    
                    notify_admin_forgot_password(user)
                    
                    messages.success(request, "📧 Un email de réinitialisation a été envoyé.")
            except User.DoesNotExist:
                messages.success(request, "📧 Si cet email existe, un lien de réinitialisation a été envoyé.")
            return redirect('login')
    else:
        form = ForgotPasswordForm()
    return render(request, 'inventory/forgot_password.html', {'form': form})


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
            
            messages.success(request, "✅ Votre mot de passe a été réinitialisé.")
            return redirect('login')
    else:
        form = ResetPasswordForm()
    
    return render(request, 'inventory/reset_password.html', {'form': form, 'token': token})

# 🔐 ========== OTP PASSWORD CHANGE AFTER LOGIN ==========
def request_otp_for_password_change(request):
    """طلب OTP لتغيير كلمة السر بعد تسجيل الدخول"""
    if not request.user.is_authenticated:
        return redirect('login')
    
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
        
        messages.success(request, "📧 Un code OTP a été envoyé à votre email")
        return redirect('change_password_with_otp_after_login')
    
    return render(request, 'inventory/request_otp_pw_change.html')


def change_password_with_otp_after_login(request):
    """تغيير كلمة السر بعد التحقق من OTP"""
    if not request.user.is_authenticated:
        return redirect('login')
    
    stored_otp = request.session.get('change_pw_otp')
    expires = request.session.get('change_pw_otp_expires', 0)
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "❌ Code OTP expiré")
        return redirect('request_otp_for_password_change')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if otp_code != stored_otp:
            messages.error(request, "❌ Code OTP invalide")
            return render(request, 'inventory/change_password_otp.html', {'require_otp': True})
        
        if new_password != confirm_password:
            messages.error(request, "❌ Les mots de passe ne correspondent pas")
            return render(request, 'inventory/change_password_otp.html', {'require_otp': False})
        
        if len(new_password) < 8:
            messages.error(request, "❌ 8 caractères minimum")
            return render(request, 'inventory/change_password_otp.html', {'require_otp': False})
        
        # Changer le mot de passe
        user = request.user
        user.set_password(new_password)
        user.save()
        
        # Mettre à jour le profil
        if hasattr(user, 'profil'):
            user.profil.must_change_password = False
            user.profil.password_changed_at = timezone.now()
            user.profil.save()
        
        # Nettoyer la session
        for key in ['change_pw_otp', 'change_pw_otp_expires']:
            if key in request.session:
                del request.session[key]
        
        # Re-authentifier
        update_session_auth_hash(request, user)
        
        messages.success(request, "✅ Votre mot de passe a été changé avec succès")
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
                    messages.success(request, '✅ Mot de passe mis à jour.')
                    notify_admin_password_change(user)
                else:
                    messages.error(request, '❌ 8 caractères minimum.')
            else:
                messages.error(request, '❌ Les mots de passe ne correspondent pas.')
        
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
            messages.success(request, f"✅ Produit '{produit.designation}' supprimé.")
        except ProtectedError:
            messages.error(request, f"❌ Impossible de supprimer '{produit.designation}'")
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
        messages.success(request, f"✅ Client '{client.designation}' supprimé")
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
        messages.success(request, f"✅ Fournisseur '{fournisseur.designation}' supprimé")
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
        
        # التحقق من وجود المستخدم
        if User.objects.filter(username=username).exists():
            messages.error(request, f"❌ Nom d'utilisateur '{username}' déjà pris")
            return redirect('user_create')
        
        # إنشاء المستخدم
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name
        )
        
        # تعيين الصلاحيات
        user.is_staff = is_staff or is_superuser
        user.is_superuser = is_superuser
        user.save()
        
        # توليد كلمة سر مؤقتة
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
                'role': role,
                'tel': tel,
                'is_banned': False,
                'failed_login_attempts': 0
            }
        )
        
        # إرسال إيميل للمستخدم
        from .utils import send_welcome_email, notify_admin_new_user
        send_welcome_email(user, temp_password)
        notify_admin_new_user(user, temp_password)
        
        # تخزين في session
        request.session['new_user_id'] = user.id
        request.session['new_user_temp_password'] = temp_password
        
        messages.success(request, f"✅ Utilisateur '{username}' créé avec succès")
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
            
            messages.success(request, f"✅ Utilisateur '{user.username}' créé")
            return redirect('user_list')
    else:
        form = AdminUserCreationForm()
    return render(request, 'inventory/admin_create_user.html', {'form': form})


def user_created_info(request):
    """صفحة عرض معلومات المستخدم الجديد"""
    user_id = request.session.get('new_user_id')
    temp_password = request.session.get('new_user_temp_password')
    
    if not user_id or not temp_password:
        return redirect('user_list')
    
    user = get_object_or_404(User, pk=user_id)
    
    # مسح الجلسة بعد العرض
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
        
        messages.success(request, f"✅ Utilisateur '{user.username}' mis à jour")
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
        
        messages.success(request, f"✅ Utilisateur '{user.username}' mis à jour")
        return redirect('user_list')
    
    return render(request, 'inventory/user_edit_secure.html', {'user': user, 'profil': profil})


@user_passes_test(lambda u: u.is_superuser)
def delete_user(request, pk):
    user = get_object_or_404(User, pk=pk)
    
    if user == request.user:
        messages.error(request, "❌ Vous ne pouvez pas supprimer votre propre compte")
        return redirect('user_list')
    
    if user.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
        messages.error(request, "❌ Impossible de supprimer le dernier administrateur")
        return redirect('user_list')
    
    if request.method == 'POST':
        username = user.username
        if hasattr(user, 'profil'):
            user.profil.delete()
        user.delete()
        messages.success(request, f"✅ Utilisateur '{username}' supprimé")
        return redirect('user_list')
    
    return render(request, 'inventory/user_confirm_delete.html', {'user_obj': user})


@user_passes_test(lambda u: u.is_superuser)
def toggle_user_ban(request, user_id):
    """Activer ou désactiver le bannissement d'un utilisateur"""
    profil = get_object_or_404(Utilisateur, id=user_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        duration = request.POST.get('duration')
        
        if action == 'ban':
            profil.is_banned = True
            if duration and duration.isdigit():
                profil.ban_until = timezone.now() + timezone.timedelta(minutes=int(duration))
            else:
                profil.ban_until = None  # Bannissement permanent
            messages.success(request, f"✅ Utilisateur '{profil.user.username}' a été banni.")
        elif action == 'unban':
            profil.is_banned = False
            profil.ban_until = None
            profil.failed_login_attempts = 0
            messages.success(request, f"✅ Utilisateur '{profil.user.username}' a été débanni.")
        
        profil.save()
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
            messages.error(request, '❌ Sélectionnez un fournisseur')
            return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
        
        fournisseur = Fournisseur.objects.filter(pk=fournisseur_id).first()
        if not fournisseur:
            messages.error(request, '❌ Fournisseur introuvable')
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
                messages.error(request, f"❌ Quantité invalide ligne {i+1}")
                return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
            
            if qte <= 0:
                messages.error(request, f"❌ Quantité doit être > 0 ligne {i+1}")
                return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
            
            produit = Produit.objects.filter(pk=prod_id).first()
            if not produit:
                messages.error(request, f"❌ Produit introuvable ligne {i+1}")
                return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
            
            lignes_data.append((produit, qte))
        
        if not lignes_data:
            messages.error(request, '❌ Aucune ligne valide')
            return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})
        
        bon = BonEntree.objects.create(fournisseur=fournisseur, utilisateur=utilisateur_obj, date_e=timezone.now())
        
        for produit, qte in lignes_data:
            LigneEntree.objects.create(bon=bon, produit=produit, qte_e=qte)
            produit.qte_stock += qte
            produit.save()
        
        messages.success(request, f"✅ Bon d'entrée #{bon.num_e} créé")
        return redirect('bon_entree_list')
    
    return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})


@login_required
def bon_entree_detail(request, pk):
    bon = get_object_or_404(BonEntree, pk=pk)
    if not request.user.is_superuser and bon.utilisateur.user != request.user:
        return HttpResponseForbidden("Accès interdit")
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
        messages.success(request, f"✅ Bon d'entrée #{pk} supprimé")
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
            messages.error(request, '❌ Sélectionnez un client')
            return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
        
        client = Client.objects.filter(pk=client_id).first()
        if not client:
            messages.error(request, '❌ Client introuvable')
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
                messages.error(request, f"❌ Quantité invalide ligne {i+1}")
                return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
            
            if qte <= 0:
                messages.error(request, f"❌ Quantité doit être > 0 ligne {i+1}")
                return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
            
            produit = Produit.objects.filter(pk=prod_id).first()
            if not produit:
                messages.error(request, f"❌ Produit introuvable ligne {i+1}")
                return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
            
            if qte > produit.qte_stock:
                messages.error(request, f"❌ Stock insuffisant pour '{produit.designation}'. Disponible: {produit.qte_stock}")
                return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
            
            lignes_data.append((produit, qte))
        
        if not lignes_data:
            messages.error(request, '❌ Aucune ligne valide')
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
            messages.warning(request, f"⚠️ Stock faible : {', '.join(low_stock_products)}")
        
        messages.success(request, f"✅ Bon de sortie #{bon.num_s} créé")
        return redirect('bon_sortie_detail', pk=bon.pk)
    
    return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})


@login_required
def bon_sortie_detail(request, pk):
    bon = get_object_or_404(BonSortie, pk=pk)
    if not request.user.is_superuser and bon.utilisateur.user != request.user:
        return HttpResponseForbidden("Accès interdit")
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
        messages.success(request, f"✅ Bon de sortie #{pk} supprimé")
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
            messages.success(request, "✅ OTP désactivé")
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
                    messages.error(request, "❌ Code OTP invalide")
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
                
                # Top produits
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
                
                # Top fournisseurs
                fournisseur_totals = LigneEntree.objects.filter(bon__in=entrees).values(
                    'bon__fournisseur__num_f', 'bon__fournisseur__designation'
                ).annotate(total_qte=Sum('qte_e')).order_by('-total_qte')[:5]
                
                for f in fournisseur_totals:
                    top_fournisseurs.append({
                        'num': f['bon__fournisseur__num_f'],
                        'name': f['bon__fournisseur__designation'],
                        'total_qte': f['total_qte'],
                    })
                
                # Top clients
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
    """طلب OTP لتغيير كلمة السر"""
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
            send_otp_email(user, otp_code, "réinitialiser votre mot de passe")
            
            messages.success(request, "📧 Un code OTP a été envoyé à votre email")
            return redirect('change_password_with_otp')
        except User.DoesNotExist:
            messages.error(request, "❌ Utilisateur non trouvé")
    
    return render(request, 'inventory/request_otp.html')


def change_password_with_otp(request):
    """تغيير كلمة السر مع التحقق من OTP"""
    user_id = request.session.get('reset_user_id')
    
    if not user_id:
        return redirect('request_password_change_otp')
    
    user = get_object_or_404(User, pk=user_id)
    stored_otp = request.session.get('reset_otp')
    expires = request.session.get('reset_otp_expires', 0)
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "❌ Code OTP expiré")
        return redirect('request_password_change_otp')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if otp_code != stored_otp:
            messages.error(request, "❌ Code OTP invalide")
            return render(request, 'inventory/change_password.html', {'require_otp': True})
        
        if new_password != confirm_password:
            messages.error(request, "❌ Les mots de passe ne correspondent pas")
            return render(request, 'inventory/change_password.html', {'require_otp': False})
        
        if len(new_password) < 8:
            messages.error(request, "❌ 8 caractères minimum")
            return render(request, 'inventory/change_password.html', {'require_otp': False})
        
        user.set_password(new_password)
        user.save()
        
        if hasattr(user, 'profil'):
            user.profil.must_change_password = False
            user.profil.save()
        
        for key in ['reset_user_id', 'reset_otp', 'reset_otp_expires']:
            if key in request.session:
                del request.session[key]
        
        messages.success(request, "✅ Mot de passe changé avec succès")
        return redirect('login')
    
    return render(request, 'inventory/change_password.html', {'require_otp': True})

# ========== CHANGE PASSWORD WITH OTP ==========
@login_required
def change_password_request(request):
    """الخطوة 1: طلب تغيير كلمة السر مع التحقق من القديمة"""
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        # التحقق من صحة كلمة السر القديمة
        if not request.user.check_password(old_password):
            messages.error(request, "❌ Mot de passe actuel incorrect")
            return redirect('change_password_request')
        
        # التحقق من تطابق كلمة السر الجديدة
        if new_password != confirm_password:
            messages.error(request, "❌ Les mots de passe ne correspondent pas")
            return redirect('change_password_request')
        
        # التحقق من طول كلمة السر
        if len(new_password) < 8:
            messages.error(request, "❌ Le mot de passe doit contenir au moins 8 caractères")
            return redirect('change_password_request')
        
        # تخزين كلمة السر الجديدة في session
        request.session['new_password'] = new_password
        
        # توليد وإرسال OTP
        user = request.user
        profil = get_user_profile(user)
        
        if not profil.otp_secret:
            profil.otp_secret = pyotp.random_base32()
            profil.save()
        
        totp = pyotp.TOTP(profil.otp_secret)
        otp_code = totp.now()
        
        request.session['change_pw_otp'] = otp_code
        request.session['change_pw_otp_expires'] = (timezone.now() + timezone.timedelta(minutes=5)).timestamp()
        
        # إرسال OTP بالبريد
        from .utils import send_otp_email
        send_otp_email(user, otp_code, "changer votre mot de passe")
        
        messages.success(request, "📧 Un code OTP a été envoyé à votre email")
        return redirect('change_password_otp_verify')
    
    return render(request, 'inventory/change_password_request.html')


@login_required
def change_password_otp_verify(request):
    """الخطوة 2: التحقق من OTP وتغيير كلمة السر"""
    stored_otp = request.session.get('change_pw_otp')
    expires = request.session.get('change_pw_otp_expires', 0)
    new_password = request.session.get('new_password')
    
    if not stored_otp or not new_password:
        messages.error(request, "❌ Session expirée, veuillez recommencer")
        return redirect('change_password_request')
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "❌ Code OTP expiré, veuillez recommencer")
        return redirect('change_password_request')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if otp_code != stored_otp:
            messages.error(request, "❌ Code OTP invalide")
            return redirect('change_password_otp_verify')
        
        # OTP correct, changer le mot de passe
        user = request.user
        user.set_password(new_password)
        user.save()
        
        # Mettre à jour le profil
        if hasattr(user, 'profil'):
            user.profil.must_change_password = False
            user.profil.password_changed_at = timezone.now()
            user.profil.save()
        
        # Nettoyer la session
        for key in ['change_pw_otp', 'change_pw_otp_expires', 'new_password']:
            if key in request.session:
                del request.session[key]
        
        # Re-authentifier
        update_session_auth_hash(request, user)
        
        # إشعار للأدمن
        from .utils import notify_admin_password_change
        notify_admin_password_change(user)
        
        messages.success(request, "✅ Votre mot de passe a été changé avec succès")
        return redirect('home')
    
    return render(request, 'inventory/change_password_otp_verify.html')


# ========== RESET PASSWORD VIA EMAIL (Forgot) ==========
def reset_password_request(request):
    """طلب إعادة تعيين كلمة السر عبر البريد"""
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email)
            if hasattr(user, 'profil'):
                profil = user.profil
                
                # Générer un token unique
                token = secrets.token_urlsafe(32)
                profil.reset_password_token = token
                profil.reset_token_expires = timezone.now() + timezone.timedelta(hours=24)
                profil.save()
                
                reset_link = request.build_absolute_uri(reverse('reset_password_with_otp', args=[token]))
                
                from .utils import send_email_to_user
                send_email_to_user(user, 
                    '🔐 Réinitialisation de votre mot de passe',
                    f'Bonjour {user.username},\n\nCliquez sur le lien suivant pour réinitialiser votre mot de passe:\n{reset_link}\n\nCe lien expire dans 24 heures.'
                )
                
                messages.success(request, "📧 Un email de réinitialisation a été envoyé")
                return redirect('login')
        except User.DoesNotExist:
            pass
        messages.success(request, "📧 Si cet email existe, un lien de réinitialisation a été envoyé")
        return redirect('login')
    
    return render(request, 'inventory/reset_password_request.html')


def reset_password_with_otp(request, token):
    """إعادة تعيين كلمة السر مع OTP"""
    try:
        profil = Utilisateur.objects.get(reset_password_token=token, reset_token_expires__gt=timezone.now())
        user = profil.user
    except Utilisateur.DoesNotExist:
        messages.error(request, "❌ Lien invalide ou expiré")
        return redirect('login')
    
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if new_password != confirm_password:
            messages.error(request, "❌ Les mots de passe ne correspondent pas")
            return render(request, 'inventory/reset_password_with_otp.html', {'token': token})
        
        if len(new_password) < 8:
            messages.error(request, "❌ 8 caractères minimum")
            return render(request, 'inventory/reset_password_with_otp.html', {'token': token})
        
        # Stocker le nouveau mot de passe
        request.session['reset_new_password'] = new_password
        request.session['reset_user_id'] = user.id
        request.session['reset_token'] = token
        
        # Envoyer OTP
        if not profil.otp_secret:
            profil.otp_secret = pyotp.random_base32()
            profil.save()
        
        totp = pyotp.TOTP(profil.otp_secret)
        otp_code = totp.now()
        
        request.session['reset_otp'] = otp_code
        request.session['reset_otp_expires'] = (timezone.now() + timezone.timedelta(minutes=5)).timestamp()
        
        from .utils import send_otp_email
        send_otp_email(user, otp_code, "réinitialiser votre mot de passe")
        
        return redirect('reset_password_otp_verify')
    
    return render(request, 'inventory/reset_password_with_otp.html', {'token': token})


def reset_password_otp_verify(request):
    """التحقق من OTP وإتمام إعادة تعيين كلمة السر"""
    user_id = request.session.get('reset_user_id')
    new_password = request.session.get('reset_new_password')
    stored_otp = request.session.get('reset_otp')
    expires = request.session.get('reset_otp_expires', 0)
    token = request.session.get('reset_token')
    
    if not user_id or not new_password or not stored_otp:
        messages.error(request, "❌ Session expirée")
        return redirect('login')
    
    if timezone.now().timestamp() > expires:
        messages.error(request, "❌ Code OTP expiré")
        return redirect('login')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        
        if otp_code != stored_otp:
            messages.error(request, "❌ Code OTP invalide")
            return render(request, 'inventory/reset_password_otp_verify.html')
        
        # Changer le mot de passe
        user = get_object_or_404(User, pk=user_id)
        user.set_password(new_password)
        user.save()
        
        # Nettoyer le token
        if hasattr(user, 'profil'):
            user.profil.reset_password_token = None
            user.profil.reset_token_expires = None
            user.profil.must_change_password = False
            user.profil.save()
        
        # Nettoyer la session
        for key in ['reset_user_id', 'reset_new_password', 'reset_otp', 'reset_otp_expires', 'reset_token']:
            if key in request.session:
                del request.session[key]
        
        messages.success(request, "✅ Votre mot de passe a été réinitialisé avec succès")
        return redirect('login')
    
    return render(request, 'inventory/reset_password_otp_verify.html')

from django.http import HttpResponse
from django.template.loader import get_template
from django.utils import timezone
from xhtml2pdf import pisa
import io
from .models import BonEntree, BonSortie, LigneEntree, LigneSortie
from django.db.models import Sum
from django.utils.dateparse import parse_date
from django.utils import timezone

def generate_pdf_report(request):
    """Generate PDF report for the selected period"""
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    from .models import BonEntree, BonSortie, LigneEntree, LigneSortie
    from django.db.models import Sum
    from django.utils.dateparse import parse_date
    
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
            
            # Top produits
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
            
            # Top fournisseurs
            fournisseur_totals = LigneEntree.objects.filter(bon__in=entrees).values(
                'bon__fournisseur__num_f', 'bon__fournisseur__designation'
            ).annotate(total_qte=Sum('qte_e')).order_by('-total_qte')[:10]
            
            for f in fournisseur_totals:
                top_fournisseurs.append({
                    'num': f['bon__fournisseur__num_f'],
                    'name': f['bon__fournisseur__designation'],
                    'total_qte': f['total_qte'] or 0,
                })
            
            # Top clients
            client_totals = LigneSortie.objects.filter(bon__in=sorties).values(
                'bon__client__code_cl', 'bon__client__designation'
            ).annotate(total_qte=Sum('qte_s')).order_by('-total_qte')[:10]
            
            for c in client_totals:
                top_clients.append({
                    'code': c['bon__client__code_cl'],
                    'name': c['bon__client__designation'],
                    'total_qte': c['total_qte'] or 0,
                })
    
    # ========== IMPORTANT: CONTEXT AVEC USER ==========
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
        'user': request.user,  # ← تأكد من وجود هذا السطر
    }
    
    from django.template.loader import get_template
    import io
    from xhtml2pdf import pisa
    
    template = get_template('inventory/report_pdf.html')
    html = template.render(context)
    
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)
    
    if not pdf.err:
        from django.http import HttpResponse
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        filename = f"rapport_{start_date}_{end_date}.pdf" if start_date and end_date else "rapport.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    
    return HttpResponse("Erreur lors de la generation du PDF", status=500)