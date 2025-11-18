# tracker/utils/request_helpers.py
"""
Request utility functions for TimeTracker.

Simple helpers for extracting information from Django requests.
"""


def _client_ip(request):
    """
    Extract client IP address from Django request.
    
    Handles X-Forwarded-For header properly for reverse proxy setups
    (nginx, Apache, Cloudflare, etc).
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        str: Client IP address
        
    Examples:
        >>> _client_ip(request)
        '192.168.1.100'
        
        >>> # Behind reverse proxy with X-Forwarded-For:
        >>> _client_ip(request)
        '203.0.113.195'  # Original client IP (not proxy IP)
    """
    # X-Forwarded-For header format: "client, proxy1, proxy2"
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Take the first IP (original client)
        ip = x_forwarded_for.split(',')[0].strip()
        return ip
    
    # Fallback to REMOTE_ADDR (direct connection)
    return request.META.get('REMOTE_ADDR', '')


def get_user_agent(request):
    """
    Extract User-Agent string from request.
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        str: User-Agent string or empty string
    """
    return request.META.get('HTTP_USER_AGENT', '')


def get_referer(request):
    """
    Extract HTTP Referer from request.
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        str: Referer URL or empty string
    """
    return request.META.get('HTTP_REFERER', '')