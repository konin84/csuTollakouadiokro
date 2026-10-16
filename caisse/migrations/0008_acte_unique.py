import unicodedata

from django.db import migrations, models


def _key(name):
    text = unicodedata.normalize("NFKD", name or "")
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).casefold().split())


def fill_name_key(apps, schema_editor):
    """Remplit la clé des actes existants ; en cas de doublon, le libellé du suivant est complété par son code."""
    Act = apps.get_model("caisse", "Act")
    seen = set()
    for act in Act.objects.order_by("id"):
        key = _key(act.name)
        if key in seen:
            act.name = f"{act.name} ({act.code})"
            key = _key(act.name)
        seen.add(key)
        act.name_key = key
        act.save(update_fields=["name", "name_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("caisse", "0007_sans_produit_consomme"),
    ]

    operations = [
        migrations.AddField(
            model_name="act",
            name="name_key",
            field=models.CharField(default="", editable=False, max_length=120),
            preserve_default=False,
        ),
        migrations.RunPython(fill_name_key, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="act",
            name="name_key",
            field=models.CharField(editable=False, max_length=120, unique=True),
        ),
    ]
