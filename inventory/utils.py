# inventory/utils.py
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Notification, Utilisateur

import requests

def send_email_to_user(user, subject, message):
    if not user.email:
        print(f"[WARNING] {user.username} n'a pas d'email")
        return False
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": settings.BREVO_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "sender": {"name": "GestionDeStock", "email": settings.DEFAULT_FROM_EMAIL},
                "to": [{"email": user.email}],
                "subject": subject,
                "textContent": message
            }
        )
        if response.status_code == 201:
            print(f"[SUCCESS] Email envoyé à {user.email}")
            return True
        else:
            print(f"[ERROR] Brevo API error: {response.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Erreur email: {e}")
        return False

def send_email_to_admins(subject, message):
    """إرسال إيميل لجميع الأدمن"""
    admins = User.objects.filter(is_superuser=True)
    admin_emails = [admin.email for admin in admins if admin.email]
    
    if admin_emails:
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                admin_emails,
                fail_silently=False,
            )
            print(f"[SUCCESS] Email envoyé aux admins: {admin_emails}")
            return True
        except Exception as e:
            print(f"[ERROR] Erreur email admin: {e}")
            return False
    return False

def send_welcome_email(user, temp_password):
    """إرسال إيميل ترحيبي مع كلمة السر المؤقتة"""
    subject = "[INFO] Votre compte a été créé"
    message = f"""
Bonjour {user.username},

Votre compte a été créé avec succès.

[INFO] Mot de passe temporaire : {temp_password}

Instructions :
1. Connectez-vous avec ce mot de passe temporaire
2. Un code OTP vous sera envoyé par email
3. Saisissez le code OTP pour vérifier votre identité
4. Choisissez votre nouveau mot de passe

Lien de connexion : https://gestion-de-stock-pido.onrender.com/login/


Attention: Ce mot de passe est temporaire. Vous devrez le changer lors de votre première connexion.

---
Ceci est un message automatique.
"""
    return send_email_to_user(user, subject, message)

def send_otp_email(user, otp_code, purpose="connexion"):
    """إرسال كود OTP للمستخدم"""
    subject = f"[SECURITY] Code OTP pour {purpose}"
    message = f"""
Bonjour {user.username},

Votre code OTP pour {purpose} est : {otp_code}

Ce code expire dans 5 minutes.

Si vous n'avez pas demandé cette action, ignorez cet email.
"""
    return send_email_to_user(user, subject, message)

def notify_admin_new_user(user, temp_password):
    """إشعار الأدمن عند إنشاء مستخدم جديد"""
    subject = "[ADMIN] Nouvel utilisateur créé"
    message = f"""
Bonjour administrateur,

Un nouvel utilisateur a été créé :

[INFO] Nom d'utilisateur : {user.username}
[INFO] Email : {user.email}
[INFO] Mot de passe temporaire : {temp_password}
[INFO] Date : {timezone.now().strftime('%d/%m/%Y à %H:%M:%S')}

---
Ceci est un message automatique.
"""
    return send_email_to_admins(subject, message)

def notify_admins_password_change(user):
    """
    Create a system notification for all administrators when a user changes their password.
    """
    admins = Utilisateur.objects.filter(user__is_superuser=True)
    if not admins:
        return
    
    message = f"L'utilisateur '{user.username}' a changé son mot de passe."
    link = f"/users/{user.username}/history/"  # adapt to your URL name if needed
    
    for admin in admins:
        Notification.objects.create(
            recipient=admin,
            type='password_change',
            title='🔐 Changement de mot de passe',
            message=message,
            link=link,
            is_read=False
        )

def notify_admin_password_change(user):
    """إشعار الأدمن عند تغيير كلمة السر"""
    subject = "[ADMIN] Changement de mot de passe"
    message = f"""
Bonjour administrateur,

L'utilisateur '{user.username}' a changé son mot de passe.

[INFO] Date et heure : {timezone.now().strftime('%d/%m/%Y à %H:%M:%S')}
[INFO] Nom d'utilisateur : {user.username}
[INFO] Email : {user.email}

---
Ceci est un message automatique.
"""
    return send_email_to_admins(subject, message)

def notify_admin_forgot_password(user):
    """إشعار الأدمن عند طلب نسيان كلمة السر"""
    subject = "[ADMIN] Demande de réinitialisation de mot de passe"
    message = f"""
Bonjour administrateur,

L'utilisateur '{user.username}' a demandé la réinitialisation de son mot de passe.

[INFO] Date et heure : {timezone.now().strftime('%d/%m/%Y à %H:%M:%S')}
[INFO] Nom d'utilisateur : {user.username}
[INFO] Email : {user.email}

Un email de réinitialisation a été envoyé à l'utilisateur.

---
Ceci est un message automatique.
"""
    return send_email_to_admins(subject, message)