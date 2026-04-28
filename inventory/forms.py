from django import forms
from django.contrib.auth.models import User

from .models import Produit, Utilisateur


class ProduitForm(forms.ModelForm):
    class Meta:
        model = Produit
        fields = ['designation', 'qte_stock', 'stock_alerte']
        widgets = {
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
            'qte_stock': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'stock_alerte': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }


class AdminUserCreationForm(forms.ModelForm):
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput,
        required=False,
        help_text='Enter a password for new users, or leave blank to keep the current password when editing.',
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput,
        required=False,
        help_text='Confirm the password if setting or changing it.',
    )

    role = forms.CharField(
        max_length=50,
        required=False,
        help_text='Role (e.g. manager, vendor)',
        error_messages={
            'max_length': 'Role must contain 50 characters or fewer.',
        }
    )
    tel = forms.CharField(
        max_length=50,
        required=False,
        help_text='Phone number (optional)',
        error_messages={
            'max_length': 'Phone number must contain 50 characters or fewer.',
        }
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'is_staff', 'is_superuser']
        field_order = ['username', 'email', 'role', 'tel', 'is_staff', 'is_superuser', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.help_text = ''

        if self.instance and self.instance.pk:
            self.fields['password1'].required = False
            self.fields['password2'].required = False
        else:
            self.fields['password1'].required = True
            self.fields['password2'].required = True

        for field_name, field in self.fields.items():
            existing_class = field.widget.attrs.get('class', '').strip()
            widget_classes = []

            if getattr(field.widget, 'input_type', '') == 'checkbox':
                widget_classes.append('form-check-input')
            else:
                widget_classes.append('form-control')

            if self.is_bound and self.errors.get(field_name):
                widget_classes.append('is-invalid')

            if existing_class:
                widget_classes.insert(0, existing_class)

            field.widget.attrs['class'] = ' '.join(widget_classes).strip()

    def clean_username(self):
        username = self.cleaned_data.get('username')
        users = User.objects.filter(username=username)
        if self.instance and self.instance.pk:
            users = users.exclude(pk=self.instance.pk)
        if users.exists():
            raise forms.ValidationError('A user with that username already exists.')
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if self.instance and self.instance.pk:
            if password1 or password2:
                if not password1 or not password2:
                    raise forms.ValidationError('Both password fields are required when changing the password.')
                if password1 != password2:
                    raise forms.ValidationError('The two password fields do not match.')
        else:
            if not password1 or not password2:
                raise forms.ValidationError('Both password fields are required for new users.')
            if password1 != password2:
                raise forms.ValidationError('The two password fields do not match.')

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password1')
        if password:
            user.set_password(password)
        elif self.instance and self.instance.pk:
            user.password = self.instance.password
        if commit:
            user.save()
        return user

from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.validators import MinLengthValidator
import re

class CustomUserCreationForm(UserCreationForm):
    """Formulaire de création d'utilisateur par l'admin"""
    email = forms.EmailField(required=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
    
    def save(self, commit=True):
        user = super().save(commit=False)
        # Générer un mot de passe temporaire
        temp_password = User.objects.make_random_password(length=10)
        user.set_password(temp_password)
        if commit:
            user.save()
            # Créer le profil Utilisateur associé
            from .models import Utilisateur
            Utilisateur.objects.create(
                username=user.username,
                password=user.password,
                must_change_password=True,  
                role='user'
            )
        return user, temp_password


class ForcePasswordChangeForm(forms.Form):
    """Formulaire pour forcer le changement de mot de passe"""
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Nouveau mot de passe'}),
        validators=[MinLengthValidator(8)],
        label='Nouveau mot de passe'
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirmer le mot de passe'}),
        label='Confirmer le mot de passe'
    )
    
    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if new_password and confirm_password and new_password != confirm_password:
            raise forms.ValidationError("Les mots de passe ne correspondent pas.")
        
        # Vérifier la complexité
        if new_password:
            if len(new_password) < 8:
                raise forms.ValidationError("Le mot de passe doit contenir au moins 8 caractères.")
            if not any(c.isupper() for c in new_password):
                raise forms.ValidationError("Le mot de passe doit contenir au moins une majuscule.")
            if not any(c.isdigit() for c in new_password):
                raise forms.ValidationError("Le mot de passe doit contenir au moins un chiffre.")
        
        return cleaned_data


class ForgotPasswordForm(forms.Form):
    """Formulaire pour demander réinitialisation"""
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Entrez votre email'}))


class ResetPasswordForm(forms.Form):
    """Formulaire pour réinitialiser le mot de passe"""
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Nouveau mot de passe'}),
        validators=[MinLengthValidator(8)]
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirmer le mot de passe'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('new_password') != cleaned_data.get('confirm_password'):
            raise forms.ValidationError("Les mots de passe ne correspondent pas.")
        return cleaned_data


class AdminOTPForm(forms.Form):
    """Formulaire pour l'OTP admin"""
    otp_code = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Code à 6 chiffres'})
    )