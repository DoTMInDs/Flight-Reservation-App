import os
from celery import Celery
from .schedules import CELERY_BEAT_SCHEDULE

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'flyres.settings')

app = Celery('flyres')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Setup beat schedule from centralized configuration
app.conf.beat_schedule = CELERY_BEAT_SCHEDULE

# Additional Celery configuration
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Task routes
    task_routes={
        'flyres.tasks.reservation_tasks.*': {
            'queue': 'reservations',
        },
        'flyres.tasks.reporting_tasks.*': {
            'queue': 'reports',
        },
        'flyres.tasks.monitoring_tasks.*': {
            'queue': 'monitoring',
        },
    },
    
    # Worker settings
    worker_max_tasks_per_child=1000,
    worker_prefetch_multiplier=1,
    
    # Result backend settings
    result_expires=3600,  # 1 hour
)


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to check Celery is working"""
    print(f'Request: {self.request!r}')


# Startup hook
@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Setup periodic tasks on startup"""
    print("Celery beat scheduler configured with tasks:")
    for task_name, task_config in app.conf.beat_schedule.items():
        print(f"  - {task_name}: {task_config['task']} "
              f"every {task_config['schedule']} seconds")