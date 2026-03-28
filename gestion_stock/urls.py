from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.http import HttpResponseNotAllowed


def custom_logout(request):
    if request.method not in ('POST', 'GET'):
        return HttpResponseNotAllowed(['GET', 'POST'])
    logout(request)
    return redirect('/accounts/login/')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/logout/', custom_logout, name='logout'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('inventory.urls')),
]
