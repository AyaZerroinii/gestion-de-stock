import json
from django.http import HttpResponse, HttpResponseBadRequest
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db import IntegrityError, models, transaction
from django.http import HttpResponseRedirect, HttpResponseForbidden, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Entreprise, Produit, Utilisateur, Fournisseur, Client, BonEntree, LigneEntree, BonSortie, LigneSortie
from .forms import ProduitForm, AdminUserCreationForm
LOW_STOCK = 50 


@login_required(login_url='login')
def dashboard_admin(request):
    if not request.user.is_superuser:
        return redirect('dashboard_user')
    
    total_produits = Produit.objects.count()
    low_stock = Produit.objects.filter(qte_stock__lte=models.F('stock_alerte')).count()
    recent_entrees = BonEntree.objects.order_by('-date_e')[:5]
    recent_sorties = BonSortie.objects.order_by('-date_s')[:5]
    
    return render(request, 'inventory/dashboard_admin.html', {
        'total_produits': total_produits,
        'low_stock': low_stock,
        'recent_entrees': recent_entrees,
        'recent_sorties': recent_sorties,
    })


@login_required(login_url='login')
def dashboard_user(request):
    if request.user.is_superuser:
        return redirect('dashboard_admin')

    if not request.user.is_staff:
        return redirect('waiting_room')
    
    utilisateur_obj = Utilisateur.objects.filter(username=request.user.username).first()
    if not utilisateur_obj:
        utilisateur_obj = Utilisateur.objects.create(username=request.user.username, password='', role='user')
    
    recent_entrees = BonEntree.objects.filter(utilisateur=utilisateur_obj).order_by('-date_e')[:5]
    recent_sorties = BonSortie.objects.filter(utilisateur=utilisateur_obj).order_by('-date_s')[:5]
    
    # إضافة المتغيرات الجديدة
    all_products = Produit.objects.all().order_by('designation')
    low_stock_count = Produit.objects.filter(qte_stock__lte=models.F('stock_alerte')).count()
    
    return render(request, 'inventory/dashboard_user.html', {
        'recent_entrees': recent_entrees,
        'recent_sorties': recent_sorties,
        'all_products': all_products,
        'total_produits': all_products.count(),
        'low_stock_count': low_stock_count,
    })


@login_required(login_url='login')
def waiting_room(request):
    return render(request, 'inventory/waiting_room.html')


@login_required(login_url='login')
def home(request):
    if request.user.is_superuser:
        return HttpResponseRedirect(reverse('dashboard_admin'))

    if not request.user.is_staff:
        return HttpResponseRedirect(reverse('waiting_room'))

    return HttpResponseRedirect(reverse('dashboard_user'))


@login_required(login_url='login')
def produit_list(request):
    produits = Produit.objects.all().order_by('designation')
    return render(request, 'inventory/produit_list.html', {'produits': produits})


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
        produit.delete()
        return HttpResponseRedirect(reverse('produit_list'))
    return render(request, 'inventory/produit_confirm_delete.html', {'produit': produit})


@login_required(login_url='login')
def product_list_api(request):
    produits = Produit.objects.all().values('code_p', 'designation', 'qte_stock', 'stock_alerte')
    return JsonResponse({'produits': list(produits)})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def user_management(request):
    users = User.objects.all().order_by('username')
    edit_user = None
    is_editing = False

    if request.method == 'GET' and request.GET.get('edit'):
        edit_user = get_object_or_404(User, pk=request.GET.get('edit'))
        utilisateur_obj = Utilisateur.objects.filter(username=edit_user.username).first()
        initial = {}
        if utilisateur_obj:
            initial = {'role': utilisateur_obj.role, 'tel': utilisateur_obj.tel}
        form = AdminUserCreationForm(instance=edit_user, initial=initial)
        is_editing = True
    elif request.method == 'POST':
        edit_user_id = request.POST.get('edit_user_id')
        if edit_user_id:
            edit_user = get_object_or_404(User, pk=edit_user_id)
            old_username = edit_user.username
            form = AdminUserCreationForm(request.POST, instance=edit_user)
        else:
            old_username = None
            form = AdminUserCreationForm(request.POST)

        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                    role = form.cleaned_data.get('role', '').strip()
                    tel = form.cleaned_data.get('tel', '').strip()
                    if edit_user:
                        utilisateur_obj = Utilisateur.objects.filter(username=old_username).first()
                        if utilisateur_obj:
                            utilisateur_obj.username = user.username
                            utilisateur_obj.password = user.password
                            utilisateur_obj.role = role
                            utilisateur_obj.tel = tel
                            utilisateur_obj.save()
                        else:
                            Utilisateur.objects.create(username=user.username, password=user.password, tel=tel, role=role)
                        messages.success(request, f"Utilisateur '{user.username}' mis à jour avec succès.")
                    else:
                        Utilisateur.objects.create(username=user.username, password=user.password, tel=tel, role=role)
                        messages.success(request, f"Utilisateur '{user.username}' créé avec succès.")
                return redirect('user_management')
            except IntegrityError:
                messages.error(request, "Impossible de sauvegarder le compte utilisateur. Veuillez vérifier les informations et réessayer.")
                form.add_error(None, "Échec de l'enregistrement du profil utilisateur.")
        else:
            messages.error(request, "Veuillez corriger les erreurs du formulaire avant de soumettre.")
            is_editing = bool(edit_user)
    else:
        form = AdminUserCreationForm()

    return render(request, 'inventory/user_management.html', {
        'users': users,
        'form': form,
        'edit_user': edit_user,
        'is_editing': is_editing,
    })


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def delete_user(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        Utilisateur.objects.filter(username=user.username).delete()
        user.delete()
        return redirect('user_management')

    return render(request, 'inventory/user_confirm_delete.html', {'user_obj': user})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def data_dashboard(request):
    stats = {
        'entreprises': Entreprise.objects.count(),
        'fournisseurs': Fournisseur.objects.count(),
        'clients': Client.objects.count(),
        'produits': Produit.objects.count(),
        'bons_entree': BonEntree.objects.count(),
        'bons_sortie': BonSortie.objects.count(),
        'utilisateurs': Utilisateur.objects.count(),
    }
    return render(request, 'inventory/data_dashboard.html', {'stats': stats})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def client_list(request):
    clients = Client.objects.all().order_by('designation')
    return render(request, 'inventory/client_list.html', {'clients': clients})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def client_create(request):
    if request.method == 'POST':
        designation = request.POST.get('designation', '').strip()
        tel = request.POST.get('tel', '').strip()
        if designation:
            Client.objects.create(designation=designation, tel=tel)
            return redirect('client_list')
        return render(request, 'inventory/client_form.html', {'error': 'Veuillez saisir le nom du client.', 'designation': designation, 'tel': tel})

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
        return redirect('client_list')
    return render(request, 'inventory/client_confirm_delete.html', {'client': client})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def fournisseur_list(request):
    fournisseurs = Fournisseur.objects.all().order_by('designation')
    return render(request, 'inventory/fournisseur_list.html', {'fournisseurs': fournisseurs})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def fournisseur_create(request):
    if request.method == 'POST':
        designation = request.POST.get('designation', '').strip()
        tel = request.POST.get('tel', '').strip()
        if designation:
            Fournisseur.objects.create(designation=designation, tel=tel)
            return redirect('fournisseur_list')
        return render(request, 'inventory/fournisseur_form.html', {'error': 'Veuillez saisir le nom du fournisseur.', 'designation': designation, 'tel': tel})
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
        return redirect('fournisseur_list')
    return render(request, 'inventory/fournisseur_confirm_delete.html', {'fournisseur': fournisseur})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def entreprise_list(request):
    entreprises = Entreprise.objects.all().order_by('nom')
    return render(request, 'inventory/entreprise_list.html', {'entreprises': entreprises})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def entreprise_create(request):
    if request.method == 'POST':
        nom = request.POST.get('nom', '').strip()
        adresse = request.POST.get('adresse', '').strip()
        tel = request.POST.get('tel', '').strip()
        if nom:
            Entreprise.objects.create(nom=nom, adresse=adresse, tel=tel)
            return redirect('entreprise_list')
        return render(request, 'inventory/entreprise_form.html', {'error': 'Veuillez saisir le nom de l\'entreprise.', 'nom': nom, 'adresse': adresse, 'tel': tel})
    return render(request, 'inventory/entreprise_form.html')


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def entreprise_edit(request, pk):
    entreprise = get_object_or_404(Entreprise, pk=pk)
    if request.method == 'POST':
        nom = request.POST.get('nom', '').strip()
        adresse = request.POST.get('adresse', '').strip()
        tel = request.POST.get('tel', '').strip()
        if nom:
            entreprise.nom = nom
            entreprise.adresse = adresse
            entreprise.tel = tel
            entreprise.save()
            return redirect('entreprise_list')
        return render(request, 'inventory/entreprise_form.html', {'entreprise': entreprise, 'error': 'Veuillez saisir le nom de l\'entreprise.'})
    return render(request, 'inventory/entreprise_form.html', {'entreprise': entreprise})


@user_passes_test(lambda u: u.is_superuser, login_url='login')
def entreprise_delete(request, pk):
    entreprise = get_object_or_404(Entreprise, pk=pk)
    if request.method == 'POST':
        entreprise.delete()
        return redirect('entreprise_list')
    return render(request, 'inventory/entreprise_confirm_delete.html', {'entreprise': entreprise})


@login_required(login_url='login')
def bon_entree_list(request):
    utilisateur_obj = Utilisateur.objects.filter(username=request.user.username).first()
    if request.user.is_superuser:
        bons = BonEntree.objects.all().order_by('-date_e')
    else:
        bons = BonEntree.objects.filter(utilisateur=utilisateur_obj).order_by('-date_e')
    return render(request, 'inventory/bon_entree_list.html', {'bons': bons})


@login_required(login_url='login')
def bon_sortie_list(request):
    utilisateur_obj = Utilisateur.objects.filter(username=request.user.username).first()
    if request.user.is_superuser:
        bons = BonSortie.objects.all().order_by('-date_s')
    else:
        bons = BonSortie.objects.filter(utilisateur=utilisateur_obj).order_by('-date_s')
    return render(request, 'inventory/bon_sortie_list.html', {'bons': bons})



@login_required(login_url='login')
def bon_entree_create(request):
    fournisseurs = Fournisseur.objects.all()
    produits = Produit.objects.all()

    if request.method == 'POST':
        fournisseur_id = request.POST.get('fournisseur')
        produits_ids = request.POST.getlist('produit[]')
        qtes = request.POST.getlist('qte[]')

        # التحقق من صحة البيانات
        if not fournisseur_id:
            return render(request, 'inventory/bon_entree_form.html', {
                'fournisseurs': fournisseurs,
                'produits': produits,
                'error': 'Veuillez sélectionner un fournisseur.',
            })

        fournisseur = Fournisseur.objects.filter(pk=fournisseur_id).first()
        if not fournisseur:
            return render(request, 'inventory/bon_entree_form.html', {
                'fournisseurs': fournisseurs,
                'produits': produits,
                'error': 'Fournisseur introuvable.',
            })

        # التحقق من وجود منتجات
        if not produits_ids or not qtes or len(produits_ids) != len(qtes):
            return render(request, 'inventory/bon_entree_form.html', {
                'fournisseurs': fournisseurs,
                'produits': produits,
                'error': 'Veuillez ajouter au moins un produit avec sa quantité.',
            })

        utilisateur_obj = Utilisateur.objects.filter(username=request.user.username).first()
        if not utilisateur_obj:
            utilisateur_obj = Utilisateur.objects.create(username=request.user.username, password='', role='')

        # التحقق من صحة كل منتج وكميته
        lignes_data = []
        for i in range(len(produits_ids)):
            prod_id = produits_ids[i]
            qte_str = qtes[i]
            if not prod_id or not qte_str:
                continue
            try:
                qte = int(qte_str)
            except ValueError:
                return render(request, 'inventory/bon_entree_form.html', {
                    'fournisseurs': fournisseurs,
                    'produits': produits,
                    'error': f'Quantité invalide pour le produit n°{i+1}.',
                })

            produit = Produit.objects.filter(pk=prod_id).first()
            if not produit:
                return render(request, 'inventory/bon_entree_form.html', {
                    'fournisseurs': fournisseurs,
                    'produits': produits,
                    'error': f'Produit n°{i+1} introuvable.',
                })

            if qte <= 0:
                return render(request, 'inventory/bon_entree_form.html', {
                    'fournisseurs': fournisseurs,
                    'produits': produits,
                    'error': f'La quantité du produit "{produit.designation}" doit être supérieure à zéro.',
                })

            lignes_data.append((produit, qte))

        # إنشاء الفاتورة والسطور
        bon = BonEntree.objects.create(
            fournisseur=fournisseur,
            utilisateur=utilisateur_obj,
            date_e=timezone.now()
        )

        for produit, qte in lignes_data:
            LigneEntree.objects.create(bon=bon, produit=produit, qte_e=qte)
            produit.qte_stock += qte
            produit.save()

        return redirect('bon_entree_list')

    return render(request, 'inventory/bon_entree_form.html', {'fournisseurs': fournisseurs, 'produits': produits})

@login_required(login_url='login')
def bon_entree_detail(request, pk):
    bon = get_object_or_404(BonEntree, pk=pk)
    if not request.user.is_superuser and bon.utilisateur.username != request.user.username:
        return HttpResponseForbidden("Vous n'avez pas accès à ce bon.")
    lignes = bon.lignes.all()
    return render(request, 'inventory/bon_entree_detail.html', {'bon': bon, 'lignes': lignes})


@login_required(login_url='login')
def bon_sortie_create(request):
    clients = Client.objects.all()
    produits = Produit.objects.all()

    if request.method == 'POST':
        client_id = request.POST.get('client')
        produits_ids = request.POST.getlist('produit[]')
        qtes = request.POST.getlist('qte[]')

        # التحقق من صحة البيانات
        if not client_id:
            return render(request, 'inventory/bon_sortie_form.html', {
                'clients': clients,
                'produits': produits,
                'error': 'Veuillez sélectionner un client.',
            })
        client = Client.objects.filter(pk=client_id).first()
        if not client:
            return render(request, 'inventory/bon_sortie_form.html', {
                'clients': clients,
                'produits': produits,
                'error': 'Client introuvable.',
            })
        if not produits_ids or not qtes or len(produits_ids) != len(qtes):
            return render(request, 'inventory/bon_sortie_form.html', {
                'clients': clients,
                'produits': produits,
                'error': 'Veuillez ajouter au moins un produit avec sa quantité.',
            })

        utilisateur_obj = Utilisateur.objects.filter(username=request.user.username).first()
        if not utilisateur_obj:
            utilisateur_obj = Utilisateur.objects.create(username=request.user.username, password='', role='user')

        # تجميع المنتجات التي ستصبح منخفضة
        low_stock_products_names = []
        lignes_data = []

        for i in range(len(produits_ids)):
            prod_id = produits_ids[i]
            qte_str = qtes[i]
            if not prod_id or not qte_str:
                continue
            try:
                qte = int(qte_str)
            except ValueError:
                return render(request, 'inventory/bon_sortie_form.html', {
                    'clients': clients,
                    'produits': produits,
                    'error': f'Quantité invalide pour le produit n°{i+1}.',
                })
            produit = Produit.objects.filter(pk=prod_id).first()
            if not produit:
                return render(request, 'inventory/bon_sortie_form.html', {
                    'clients': clients,
                    'produits': produits,
                    'error': f'Produit n°{i+1} introuvable.',
                })
            if qte <= 0:
                return render(request, 'inventory/bon_sortie_form.html', {
                    'clients': clients,
                    'produits': produits,
                    'error': f'La quantité du produit "{produit.designation}" doit être supérieure à zéro.',
                })
            if qte > produit.qte_stock:
                return render(request, 'inventory/bon_sortie_form.html', {
                    'clients': clients,
                    'produits': produits,
                    'error': f'Quantité insuffisante pour "{produit.designation}". Stock disponible: {produit.qte_stock}.',
                })
            lignes_data.append((produit, qte))

        # إنشاء الفاتورة وتحديث المخزون
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

        # إضافة رسالة Toast إذا وجد منتج منخفض
        if low_stock_products_names:
            message = f"⚠️ Stock faible pour : {', '.join(low_stock_products_names)}"
            messages.add_message(request, LOW_STOCK, message)

        return redirect('bon_sortie_detail', pk=bon.pk)

    return render(request, 'inventory/bon_sortie_form.html', {'clients': clients, 'produits': produits})
@login_required(login_url='login')
def bon_sortie_detail(request, pk):
    bon = get_object_or_404(BonSortie, pk=pk)
    if not request.user.is_superuser and bon.utilisateur.username != request.user.username:
        return HttpResponseForbidden("Vous n'avez pas accès à ce bon.")
    lignes = bon.lignes.all()
    return render(request, 'inventory/bon_sortie_detail.html', {'bon': bon, 'lignes': lignes})


@csrf_exempt
@login_required(login_url='login')
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
    return JsonResponse({'code_p': produit.code_p, 'designation': produit.designation, 'qte_stock': produit.qte_stock, 'stock_alerte': produit.stock_alerte}, status=201)


@csrf_exempt
@login_required(login_url='login')
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
    return JsonResponse({'code_p': produit.code_p, 'designation': produit.designation, 'qte_stock': produit.qte_stock, 'stock_alerte': produit.stock_alerte})

