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
    error_messages = {
        'password_mismatch': 'The two password fields do not match.',
    }

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

