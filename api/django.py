import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

# Set DJANGO_SETTINGS_MODULE to the production settings loader if desired
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kissanmart.settings')

# Boot Django
import django
from django.core.wsgi import get_wsgi_application

django.setup()
application = get_wsgi_application()

# awsgi wraps a WSGI app into a function that the serverless platform can call
try:
    import awsgi
except Exception:
    awsgi = None


def handler(request, context=None):
    """Vercel Python function entrypoint.

    Vercel passes a Flask-like request object. awsgi provides a small adapter
    to convert between WSGI and the serverless event. If awsgi is not
    available, return a simple 500 response explaining the missing dependency.
    """
    if awsgi is None:
        return {
            'statusCode': 500,
            'body': 'awsgi is not installed. Add awsgi to requirements.txt.'
        }

    # Vercel's Python runtime provides a `request` with .method, .headers, .get_data(), .path, .query
    # awsgi expects a WSGI environ-like mapping; awsgi.from_flask will detect common attributes.
    # Use awsgi.response to convert WSGI response back to Vercel-friendly dict.
    return awsgi.response(application, request)
