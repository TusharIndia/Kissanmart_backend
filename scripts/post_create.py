import os
import sys
import traceback

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kissanmart.settings')

try:
    import django
    django.setup()
    from django.test import Client

    client = Client()
    path = '/api/products/products/create/'
    try:
        resp = client.post(path, data={})
        print('Status code:', resp.status_code)
        print('Content:', resp.content[:1000])
    except Exception:
        print('Exception during request:')
        traceback.print_exc()
except Exception:
    print('Error during Django setup:')
    traceback.print_exc()
