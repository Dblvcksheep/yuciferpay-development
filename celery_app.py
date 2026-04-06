from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

celery_url = os.environ['CELERY_BROKER_URL']
def make_celery(app):
    celery = Celery(
        app.import_name,
        broker=celery_url,
        backend=celery_url,
        include=["tasks"]
    )

    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
