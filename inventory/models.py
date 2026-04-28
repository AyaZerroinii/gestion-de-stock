from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Utilisateur(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Administrateur'),
        ('staff', 'Staff'),
        ('user', 'Utilisateur'),
    ]
    
    # Relation OneToOne avec User de Django (plus propre)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profil')
    tel = models.CharField(max_length=20, blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')
    
    # 🔐 Champs de sécurité
    must_change_password = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)
    ban_until = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.IntegerField(default=0)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    
    # OTP pour admin
    otp_secret = models.CharField(max_length=32, blank=True, null=True)
    otp_enabled = models.BooleanField(default=False)
    
    # Token pour reset password
    reset_password_token = models.CharField(max_length=100, blank=True, null=True)
    reset_token_expires = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return self.user.username
    
    def is_account_locked(self):
        """Vérifier si le compte est bloqué"""
        if self.is_banned:
            if self.ban_until and self.ban_until > timezone.now():
                return True, f"Compte bloqué jusqu'au {self.ban_until.strftime('%d/%m/%Y %H:%M')}"
            elif self.ban_until is None:
                return True, "Compte définitivement bloqué"
        return False, None
    
    def increment_failed_attempts(self):
        """Incrémenter les tentatives échouées"""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.is_banned = True
            self.ban_until = timezone.now() + timezone.timedelta(minutes=30)
        self.save()
    
    def reset_failed_attempts(self):
        self.failed_login_attempts = 0
        self.save()


# ========== MODÈLES EXISTANTS ==========
class Entreprise(models.Model):
    nom = models.CharField(max_length=255)
    adresse = models.TextField(blank=True, null=True)
    tel = models.CharField(max_length=20, blank=True, null=True)
    
    def __str__(self):
        return self.nom


class Produit(models.Model):
    code_p = models.AutoField(primary_key=True)
    designation = models.CharField(max_length=255)
    qte_stock = models.IntegerField(default=0)
    stock_alerte = models.IntegerField(default=5)
    
    def __str__(self):
        return f"{self.code_p} - {self.designation}"


class Fournisseur(models.Model):
    num_f = models.AutoField(primary_key=True)
    designation = models.CharField(max_length=255)
    tel = models.CharField(max_length=20, blank=True, null=True)
    
    def __str__(self):
        return self.designation


class Client(models.Model):
    code_cl = models.AutoField(primary_key=True)
    designation = models.CharField(max_length=255)
    tel = models.CharField(max_length=20, blank=True, null=True)
    
    def __str__(self):
        return self.designation


class BonEntree(models.Model):
    num_e = models.AutoField(primary_key=True)
    date_e = models.DateTimeField(auto_now_add=True)
    fournisseur = models.ForeignKey(Fournisseur, on_delete=models.CASCADE)
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.CASCADE)  # علاقة مع Utilisateur
    
    def __str__(self):
        return f"BE#{self.num_e}"


class LigneEntree(models.Model):
    bon = models.ForeignKey(BonEntree, on_delete=models.CASCADE, related_name='lignes')
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    qte_e = models.IntegerField()
    
    def __str__(self):
        return f"{self.produit.designation} x{self.qte_e}"


class BonSortie(models.Model):
    num_s = models.AutoField(primary_key=True)
    date_s = models.DateTimeField(auto_now_add=True)
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.CASCADE)  # علاقة مع Utilisateur
    
    def __str__(self):
        return f"BS#{self.num_s}"


class LigneSortie(models.Model):
    bon = models.ForeignKey(BonSortie, on_delete=models.CASCADE, related_name='lignes')
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    qte_s = models.IntegerField()
    
    def __str__(self):
        return f"{self.produit.designation} x{self.qte_s}"


class NotificationStatus(models.Model):
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.CASCADE)
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    read = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('utilisateur', 'produit')


from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """إنشاء بروفايل تلقائياً عند إنشاء مستخدم جديد"""
    if created:
        Utilisateur.objects.get_or_create(
            user=instance,
            defaults={
                'must_change_password': True,
                'role': 'admin' if instance.is_superuser else ('staff' if instance.is_staff else 'user'),
                'tel': '',
                'is_banned': False,
                'failed_login_attempts': 0
            }
        )

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """حفظ البروفايل عند حفظ المستخدم"""
    if hasattr(instance, 'profil'):
        instance.profil.save()

def is_account_locked(self):
    """Vérifier si le compte est bloqué"""
    if self.is_banned:
        if self.ban_until and self.ban_until > timezone.now():
            return True, f"Compte bloqué jusqu'au {self.ban_until.strftime('%d/%m/%Y %H:%M')}"
        elif self.ban_until is None:
            return True, "Compte définitivement bloqué. Contactez l'administrateur."
    return False, None

def is_account_locked(self):
    """Vérifier si le compte est bloqué"""
    if self.is_banned:
        if self.ban_until and self.ban_until > timezone.now():
            return True, f"Compte bloqué jusqu'au {self.ban_until.strftime('%d/%m/%Y %H:%M')}"
        elif self.ban_until is None:
            return True, "Compte définitivement bloqué. Contactez l'administrateur."
    return False, None

def increment_failed_attempts(self):
    """Incrémenter les tentatives échouées"""
    self.failed_login_attempts += 1
    if self.failed_login_attempts >= 5:
        self.is_banned = True
        self.ban_until = timezone.now() + timezone.timedelta(minutes=30)
    self.save()

def reset_failed_attempts(self):
    """Réinitialiser les tentatives échouées"""
    self.failed_login_attempts = 0
    self.save()