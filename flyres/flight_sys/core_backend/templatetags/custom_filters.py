from django import template
import re
from datetime import datetime

register = template.Library()

@register.filter
def replace(value, args):
    """
    Replaces all occurrences of arg[0] with arg[1] in value.
    Usage: {{ value|replace:"old,new" }}
    """
    if not value or not args:
        return value
    
    try:
        # Handle both string format "old,new" and direct replacement
        if isinstance(args, str) and ',' in args:
            old, new = args.split(',', 1)
            return str(value).replace(old, new)
        elif isinstance(args, str):
            # If only one arg, remove it
            return str(value).replace(args, '')
        else:
            return str(value)
    except (ValueError, AttributeError):
        return value

@register.filter
def format_duration(value):
    """
    Format ISO 8601 duration (PT5H30M) to readable format (5h 30m)
    """
    if not value:
        return ""
    
    try:
        # Remove PT prefix
        duration = str(value).replace('PT', '')
        
        hours_match = re.search(r'(\d+)H', duration)
        minutes_match = re.search(r'(\d+)M', duration)
        
        hours = hours_match.group(1) if hours_match else "0"
        minutes = minutes_match.group(1) if minutes_match else "0"
        
        parts = []
        if int(hours) > 0:
            parts.append(f"{hours}h")
        if int(minutes) > 0:
            parts.append(f"{minutes}m")
        
        return " ".join(parts) if parts else "0h"
    except:
        return str(value)

@register.filter
def format_datetime(value, format_string='%Y-%m-%d %H:%M'):
    """
    Format datetime string
    Usage: {{ flight.departure_time|format_datetime:"%H:%M" }}
    """
    if not value:
        return ""
    
    try:
        # Try to parse ISO format
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.strftime(format_string)
    except (ValueError, AttributeError):
        try:
            # Try to parse as string
            dt = datetime.strptime(str(value), '%Y-%m-%dT%H:%M:%S')
            return dt.strftime(format_string)
        except:
            return str(value)

@register.filter
def currency(value, currency_code='USD'):
    """
    Format number as currency
    Usage: {{ price.total|currency:"USD" }}
    """
    try:
        num = float(value)
        if currency_code == 'USD':
            return f"${num:,.2f}"
        else:
            return f"{currency_code} {num:,.2f}"
    except (ValueError, TypeError):
        return value

@register.filter
def multiply(value, arg):
    """
    Multiply value by arg
    Usage: {{ price|multiply:1.1 }} (for 10% increase)
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return value

@register.filter
def divide(value, arg):
    """
    Divide value by arg
    Usage: {{ total|divide:passengers }}
    """
    try:
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return value

@register.filter
def get_item(dictionary, key):
    """
    Get item from dictionary by key
    Usage: {{ flight|get_item:"duration" }}
    """
    try:
        return dictionary.get(key, '')
    except (AttributeError, TypeError):
        return ''

@register.filter
def split(value, delimiter=','):
    """
    Split string into list
    Usage: {{ airlines|split:"," }}
    """
    if not value:
        return []
    return str(value).split(delimiter)

@register.filter
def join_list(value, delimiter=', '):
    """
    Join list into string
    Usage: {{ airlines|join_list:", " }}
    """
    if not value:
        return ''
    return delimiter.join(str(item) for item in value)

@register.filter
def truncate(value, length=50):
    """
    Truncate string to specified length
    Usage: {{ description|truncate:100 }}
    """
    if not value:
        return ''
    value_str = str(value)
    if len(value_str) <= length:
        return value_str
    return value_str[:length] + '...'

@register.filter
def default_if_none(value, default_value):
    """
    Return default value if value is None
    Usage: {{ price|default_if_none:"0.00" }}
    """
    if value is None:
        return default_value
    return value

@register.filter
def airline_logo_url(airline_code):
    """
    Generate airline logo URL (placeholder)
    """
    return f"https://daisycon.io/images/airline/?width=100&height=100&color=ffffff&iata={airline_code}"

@register.filter
def flight_stops(value):
    """
    Format number of stops
    """
    try:
        stops = int(value)
        if stops == 0:
            return "Non-stop"
        elif stops == 1:
            return "1 stop"
        else:
            return f"{stops} stops"
    except:
        return "Unknown"