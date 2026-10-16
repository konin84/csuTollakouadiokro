"""Synchronise les ventes pharmacie (saisies dans la journée de caisse) avec le stock."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from caisse.models import PharmacySale

from .models import StockMovement


@receiver(post_save, sender=PharmacySale, dispatch_uid="sale_to_stock")
def sale_to_stock(sender, instance: PharmacySale, **kwargs):
    if instance.product_id:
        StockMovement.objects.update_or_create(
            sale=instance,
            defaults={
                "product_id": instance.product_id,
                "date": instance.session.date,
                "kind": StockMovement.SALE,
                "quantity": -int(instance.stock_quantity),
                "unit_cost": round(instance.product.unit_cost),
                "reference": f"Caisse du {instance.session.date:%d/%m/%Y}",
            },
        )
    else:
        StockMovement.objects.filter(sale=instance).delete()
