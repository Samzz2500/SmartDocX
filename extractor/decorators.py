"""Rate limiting and security decorators."""
from functools import wraps
from django.core.cache import cache
from django.http import HttpResponse
from django.contrib import messages
import time

def rate_limit(max_requests=10, window=60):
    """Rate limit decorator: max_requests per window seconds."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return view_func(request, *args, **kwargs)
            
            key = f"rate_limit_{request.user.id}"
            count = cache.get(key, 0)
            
            if count >= max_requests:
                messages.error(request, f"⚠️ Rate limit exceeded. Max {max_requests} requests per {window} seconds.")
                return HttpResponse("Rate limit exceeded", status=429)
            
            cache.set(key, count + 1, window)
            return view_func(request, *args, **kwargs)
        return wrapped_view
    return decorator

