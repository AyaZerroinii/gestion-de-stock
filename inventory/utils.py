from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

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
            return True
        except Exception as e:
            print(f"❌ فشل إرسال الإيميل: {e}")
            return False
    return False

def send_email_to_user(user, subject, message):
    """إرسال إيميل لمستخدم محدد"""
    if user.email:
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            return True
        except Exception as e:
            print(f"❌ فشل إرسال الإيميل: {e}")
            return False
    return False

def notify_admin_password_change(user):
    """إشعار الأدمن عند تغيير كلمة السر"""
    subject = "🔐 Changement de mot de passe"
    message = f"""
    Bonjour cher administrateur,

    L'utilisateur '{user.username}' a changé son mot de passe.

    📅 Date et heure : {timezone.now().strftime('%d/%m/%Y à %H:%M:%S')}
    👤 Nom d'utilisateur : {user.username}
    📧 Email : {user.email}

    ---
    Ceci est un message automatique.
    """
    send_email_to_admins(subject, message)

def notify_admin_forgot_password(user):
    """إشعار الأدمن عند طلب نسيان كلمة السر"""
    subject = "🔐 Demande de réinitialisation de mot de passe"
    message = f"""
    Bonjour cher administrateur,

    L'utilisateur '{user.username}' a demandé la réinitialisation de son mot de passe.

    📅 Date et heure : {timezone.now().strftime('%d/%m/%Y à %H:%M:%S')}
    👤 Nom d'utilisateur : {user.username}
    📧 Email : {user.email}

    Un email de réinitialisation a été envoyé à l'utilisateur.

    ---
    Ceci est un message automatique.
    """
    send_email_to_admins(subject, message)

def send_welcome_email(user, temp_password):
    """إرسال إيميل ترحيبي مع كلمة السر المؤقتة"""
    subject = "🎉 Bienvenue ! Votre compte a été créé"
    message = f"""
    Bonjour {user.username},

    Votre compte a été créé avec succès.

    🔑 Mot de passe temporaire : {temp_password}

    Vous devez changer votre mot de passe lors de votre première connexion.

    🔗 Lien de connexion : http://127.0.0.1:8000/login/

    ---
    Ceci est un message automatique. Veuillez ne pas y répondre.
    """
    send_email_to_user(user, subject, message)