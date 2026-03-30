"""
Centralized schedule configuration for Celery Beat tasks.
All periodic tasks should be defined here.
"""
from celery.schedules import crontab
import os

# Define schedules based on environment
def get_schedules(environment=None):
    """Get schedules based on environment"""
    if environment is None:
        environment = os.getenv('DJANGO_ENV', 'development')
    
    # Base schedules common to all environments
    base_schedules = {
        # Expire reservations every 5 minutes
        'expire-reservations-frequent': {
            'task': 'flyres.tasks.reservation_tasks.expire_reservations_task',
            'schedule': 300.0,  # 5 minutes in seconds
            'args': (100, 5),   # batch_size=100, grace_period_minutes=5
            'options': {
                'expires': 120,  # Task expires after 2 minutes
            }
        },
        
        # Clean up old audit logs daily at 2 AM
        'cleanup-audit-logs': {
            'task': 'flyres.tasks.maintenance_tasks.cleanup_audit_logs_task',
            'schedule': crontab(hour=2, minute=0),
            'args': (30,),  # Keep logs for 30 days
        },
        
        # Health check every hour
        'system-health-check': {
            'task': 'flyres.tasks.monitoring_tasks.system_health_check_task',
            'schedule': 3600.0,  # 1 hour
        },
    }
    
    # Environment-specific schedules
    environment_schedules = {
        'development': {
            # Additional dev tasks
            'test-task': {
                'task': 'flyres.tasks.test_tasks.test_periodic_task',
                'schedule': 600.0,  # 10 minutes
                'args': ('development',),
            }
        },
        'production': {
            # Production-specific optimizations
            'expire-reservations-production': {
                'task': 'flyres.tasks.reservation_tasks.expire_reservations_task',
                'schedule': 180.0,  # 3 minutes in production (more frequent)
                'args': (200, 2),   # Larger batch, smaller grace period
                'options': {
                    'expires': 90,
                    'queue': 'expiry_high_priority',
                }
            },
            
            # Generate daily reports at 1 AM
            'daily-expiry-report': {
                'task': 'flyres.tasks.reporting_tasks.generate_expiry_report_task',
                'schedule': crontab(hour=1, minute=0),
                'options': {
                    'queue': 'reports',
                }
            },
            
            # Database maintenance weekly on Sunday at 3 AM
            'weekly-maintenance': {
                'task': 'flyres.tasks.maintenance_tasks.weekly_database_maintenance_task',
                'schedule': crontab(hour=3, minute=0, day_of_week=0),  # Sunday
            },
        },
        'staging': {
            # Staging environment schedules
            'expire-reservations-staging': {
                'task': 'flyres.tasks.reservation_tasks.expire_reservations_task',
                'schedule': 600.0,  # 10 minutes in staging
                'args': (50, 10),   # Smaller batch, larger grace period
            }
        }
    }
    
    # Merge schedules
    schedules = base_schedules.copy()
    
    if environment in environment_schedules:
        env_schedule = environment_schedules[environment]
        # Merge with priority to environment-specific
        schedules.update(env_schedule)
    
    return schedules


# Quick access functions
def get_expiry_schedule(environment=None):
    """Get the expiry task schedule for current environment"""
    schedules = get_schedules(environment)
    
    # Look for expiry tasks
    expiry_tasks = [
        task_name for task_name in schedules.keys() 
        if 'expire-reservations' in task_name
    ]
    
    if expiry_tasks:
        # Return the most specific one
        for task_name in expiry_tasks:
            if environment in task_name:
                return schedules[task_name]
        return schedules[expiry_tasks[0]]
    
    # Default fallback
    return {
        'task': 'flyres.tasks.reservation_tasks.expire_reservations_task',
        'schedule': 300.0,
        'args': (100, 5),
    }


def get_all_task_names():
    """Get all scheduled task names"""
    return list(get_schedules().keys())


# Export the main schedule
CELERY_BEAT_SCHEDULE = get_schedules()