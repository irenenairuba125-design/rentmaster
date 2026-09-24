"""
WSGI config for rentmaster project.

It exposes the WSGI callable as a module-level variable named ``application``
(``app`` is an alias for hosts such as Vercel that look for that name).
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rentmaster.settings")

application = get_wsgi_application()

from django.conf import settings  # noqa: E402

if settings.DEMO_MODE:
    from rentmaster import demo

    demo.prepare()

app = application
