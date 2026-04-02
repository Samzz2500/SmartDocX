from django import template
register = template.Library()

@register.filter
def dict_get(d, key):
    """Safely get dictionary value from key with spaces."""
    if isinstance(d, dict):
        return d.get(key, "")
    return ""
