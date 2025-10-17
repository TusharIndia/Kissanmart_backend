import os
import sys
import traceback

# Ensure project root is on sys.path so 'kissanmart' package can be imported
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kissanmart.settings')
try:
    import django
    django.setup()
    from django.urls import resolve
    path = '/api/products/products/create/'
    try:
        res = resolve(path)
        print('Resolved:', res)
        print('View func:', res.func)
        print('Args:', res.args)
        print('Kwargs:', res.kwargs)
    except Exception as e:
        print('Error resolving path:')
        traceback.print_exc()
except Exception:
    print('Error during Django setup:')
    traceback.print_exc()
