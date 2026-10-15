from django.conf import settings
from django.db import models

from .audit import track


class Facility(models.Model):
    """L'établissement (FSU). Une seule ligne en pratique ; le modèle permet
    d'en gérer plusieurs plus tard (plusieurs centres d'un district)."""

    name = models.CharField("nom", max_length=200)
    short_name = models.CharField("nom court", max_length=60, blank=True)
    address = models.CharField("adresse / localité", max_length=200, blank=True)
    phone = models.CharField("téléphone", max_length=60, blank=True)
    # Soldes de départ : argent déjà en caisse le jour où l'on commence à utiliser l'application
    opening_date = models.DateField(
        "date de démarrage", null=True, blank=True,
        help_text="Premier jour suivi dans l'application. L'argent en caisse ci-dessous est celui du matin de ce jour.",
    )
    opening_cash = models.IntegerField("argent en caisse au démarrage (F)", default=0)
    cash_tolerance = models.PositiveIntegerField(
        "tolérance d'écart de caisse (F)", default=500,
        help_text="Au-delà, l'écart entre l'argent compté et le solde théorique est signalé.",
    )
    block_negative_stock = models.BooleanField(
        "bloquer la vente d'un produit sans stock", default=True,
        help_text="Décocher seulement en attendant le premier inventaire de la pharmacie.",
    )

    class Meta:
        verbose_name = "établissement"
        verbose_name_plural = "établissement"

    def __str__(self):
        return self.name

    @classmethod
    def current(cls):
        obj = cls.objects.order_by("id").first()
        if obj is None:
            obj = cls.objects.create(name="Mon établissement")
        return obj


class AuditLog(models.Model):
    ACTIONS = [
        ("create", "Création"),
        ("update", "Modification"),
        ("delete", "Suppression"),
        ("close", "Clôture"),
        ("validate", "Validation"),
        ("reopen", "Réouverture"),
        ("cancel", "Annulation"),
        ("receive", "Réception"),
        ("import", "Import"),
        ("login", "Connexion"),
    ]
    timestamp = models.DateTimeField("date", auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             verbose_name="utilisateur")
    action = models.CharField(max_length=20, choices=ACTIONS)
    model = models.CharField("objet", max_length=80)
    object_id = models.CharField(max_length=40, blank=True)
    object_repr = models.CharField("description", max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "journal d'activité"
        verbose_name_plural = "journal d'activité"

    def __str__(self):
        return f"{self.timestamp:%d/%m/%Y %H:%M} {self.user} {self.get_action_display()} {self.object_repr}"


track(Facility)
