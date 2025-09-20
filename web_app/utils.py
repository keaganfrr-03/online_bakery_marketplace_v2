from .models import ActivityLog


def log_activity(user, action, details=None, ip_address=None):
    """Create an activity log entry for a user."""
    if not user.is_authenticated:
        return

    ActivityLog.objects.create(
        user=user,
        action=action,
        details=details or "",
        ip_address=ip_address,
    )
