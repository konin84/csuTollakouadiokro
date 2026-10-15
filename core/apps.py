from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Établissement et utilisateurs"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .audit import log

        def on_login(sender, request, user, **kwargs):
            log("login", user, user=user, model="utilisateur", object_repr=user.get_username())

        user_logged_in.connect(on_login, dispatch_uid="audit_login")
