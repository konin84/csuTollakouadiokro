from .models import Facility
from .roles import RIGHTS, can


def app_context(request):
    user = request.user
    if not user.is_authenticated:
        return {"facility": Facility.objects.order_by("id").first()}
    return {
        "facility": Facility.current(),
        "perms_app": {right: can(user, right) for right in RIGHTS},
    }
