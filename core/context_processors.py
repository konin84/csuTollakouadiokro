from .models import Facility
from .roles import RIGHTS, can, user_roles


def app_context(request):
    user = request.user
    if not user.is_authenticated:
        return {"facility": Facility.objects.order_by("id").first()}
    return {
        "facility": Facility.current(),
        "perms_app": {right: can(user, right) for right in RIGHTS},
        # rôles affichés dans le menu du compte (en haut à droite)
        "roles_label": "Administrateur" if user.is_superuser else ", ".join(sorted(user_roles(user))),
    }
