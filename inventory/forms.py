from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

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


class AdminUserCreationForm(UserCreationForm):
    role = forms.CharField(max_length=50, required=False, help_text='Role (ex: manager, vendeur)')

    class Meta:
        model = User
        fields = ['username', 'email', 'is_staff', 'is_superuser', 'role']

