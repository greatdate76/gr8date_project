def can_view_private(viewer, owner_profile) -> bool:
    if getattr(viewer, "is_authenticated", False) and getattr(viewer, "is_superuser", False):
        return True

    if (
        getattr(viewer, "is_authenticated", False)
        and getattr(owner_profile, "user_id", None) == getattr(viewer, "id", None)
    ):
        return True

    return False

