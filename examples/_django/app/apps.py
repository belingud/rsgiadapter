from django.apps import AppConfig


class ExampleAppConfig(AppConfig):
    # django-stubs types default_auto_field as a cached_property; assigning
    # the standard string is correct at runtime
    default_auto_field = "django.db.models.BigAutoField"  # type: ignore[assignment]
    name = "app"
