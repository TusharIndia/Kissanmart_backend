import importlib
import sys
import os

# Ensure project root is on sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Configure Django settings env if not already set so imports referencing settings work
if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    os.environ['DJANGO_SETTINGS_MODULE'] = 'kissanmart.settings'
try:
    import django
    django.setup()
except Exception:
    pass

mods = [
    'products.api.serializers',
    'products.models',
]
for m in mods:
    try:
        importlib.import_module(m)
        print(m + ' OK')
    except Exception as e:
        print(m + ' ERROR: ' + repr(e))
        sys.exit(2)
print('IMPORTS_OK')
