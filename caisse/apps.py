from django.apps import AppConfig


class CaisseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "caisse"
    verbose_name = "Caisse"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from . import services
        from .models import CommissionRule

        # Les règles sont mises en cache pour les calculs : les oublier dès qu'une règle change.
        def clear(**kwargs):
            services.clear_caches()

        post_save.connect(clear, sender=CommissionRule, weak=False, dispatch_uid="commission_rules_cache")
        post_delete.connect(clear, sender=CommissionRule, weak=False, dispatch_uid="commission_rules_cache_del")
