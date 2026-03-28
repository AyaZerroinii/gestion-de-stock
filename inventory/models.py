from django.db import models


class Entreprise(models.Model):
    id_ent = models.AutoField(primary_key=True)
    nom = models.CharField(max_length=255)
    adresse = models.CharField(max_length=255, blank=True, null=True)
    tel = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.nom


class Utilisateur(models.Model):
    id_user = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    password = models.CharField(max_length=128)
    role = models.CharField(max_length=50)

    def __str__(self):
        return self.username


class Client(models.Model):
    code_cl = models.AutoField(primary_key=True)
    designation = models.CharField(max_length=255)
    tel = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.designation


class Fournisseur(models.Model):
    num_f = models.AutoField(primary_key=True)
    designation = models.CharField(max_length=255)
    tel = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.designation


class Produit(models.Model):
    code_p = models.AutoField(primary_key=True)
    designation = models.CharField(max_length=255)
    qte_stock = models.IntegerField(default=0)
    stock_alerte = models.IntegerField(default=0)

    def __str__(self):
        return self.designation


class BonEntree(models.Model):
    num_e = models.AutoField(primary_key=True)
    date_e = models.DateTimeField()
    fournisseur = models.ForeignKey(Fournisseur, on_delete=models.PROTECT, related_name='bons_entree')
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.PROTECT, related_name='bons_entree')

    def __str__(self):
        return f"BonEntree #{self.num_e} - {self.date_e.date()}"


class LigneEntree(models.Model):
    id_le = models.AutoField(primary_key=True)
    bon = models.ForeignKey(BonEntree, on_delete=models.CASCADE, related_name='lignes')
    produit = models.ForeignKey(Produit, on_delete=models.PROTECT, related_name='lignes_entree')
    qte_e = models.IntegerField()

    def __str__(self):
        return f"{self.qte_e} x {self.produit}"


class BonSortie(models.Model):
    num_s = models.AutoField(primary_key=True)
    date_s = models.DateTimeField()
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='bons_sortie')
    utilisateur = models.ForeignKey(Utilisateur, on_delete=models.PROTECT, related_name='bons_sortie')

    def __str__(self):
        return f"BonSortie #{self.num_s} - {self.date_s.date()}"


class LigneSortie(models.Model):
    id_ls = models.AutoField(primary_key=True)
    bon = models.ForeignKey(BonSortie, on_delete=models.CASCADE, related_name='lignes')
    produit = models.ForeignKey(Produit, on_delete=models.PROTECT, related_name='lignes_sortie')
    qte_s = models.IntegerField()

    def __str__(self):
        return f"{self.qte_s} x {self.produit}"
