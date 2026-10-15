"""Journal d'activité : qui a créé / modifié / supprimé quoi, et quand.

Les modèles suivis sont enregistrés via `track(Model)` ; les actions métier
(clôture, validation, réouverture…) sont journalisées avec `log()`.
"""
from datetime import date, datetime
from decimal import Decimal

from django.db.models.fields.files import FieldFile
from django.db.models.signals import post_delete, post_save, pre_save

from .middleware import get_current_user

IGNORED_FIELDS = {"updated_at", "created_at"}


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name or ""
    return value


def _snapshot(instance):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in IGNORED_FIELDS:
            continue
        data[str(field.verbose_name)] = _plain(getattr(instance, field.attname))
    return data


def log(action, instance=None, details=None, user=None, model=None, object_repr=None):
    from .models import AuditLog

    AuditLog.objects.create(
        user=user or get_current_user(),
        action=action,
        model=model or (instance._meta.verbose_name if instance is not None else ""),
        object_id=str(getattr(instance, "pk", "") or ""),
        object_repr=(object_repr or str(instance))[:255] if (object_repr or instance is not None) else "",
        details=details or {},
    )


def _pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._audit_before = _snapshot(old)
        except sender.DoesNotExist:
            instance._audit_before = None
    else:
        instance._audit_before = None


def _post_save(sender, instance, created, **kwargs):
    if getattr(instance, "_audit_skip", False):
        return
    after = _snapshot(instance)
    if created:
        log("create", instance, {"valeurs": after})
        return
    before = getattr(instance, "_audit_before", None) or {}
    changes = {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}
    if changes:
        log("update", instance, {"modifications": changes})


def _post_delete(sender, instance, **kwargs):
    log("delete", instance, {"valeurs": _snapshot(instance)})


def track(model):
    uid = f"audit_{model._meta.label_lower}"
    pre_save.connect(_pre_save, sender=model, dispatch_uid=uid + "_pre")
    post_save.connect(_post_save, sender=model, dispatch_uid=uid + "_post")
    post_delete.connect(_post_delete, sender=model, dispatch_uid=uid + "_del")
    return model
