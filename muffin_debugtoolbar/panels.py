"""Debug panels."""
import asyncio
import datetime as dt
import logging
import os
import platform
import re
from html import escape
from operator import itemgetter
from pprint import saferepr

import pkg_resources
from aiohttp import web
from muffin import __version__ as muffin_version

from .tbtools.tbtools import Traceback
from .utils import LoggingTrackingHandler


class DebugPanel:

    """Base class for debug panels."""

    name = None
    template = None
    has_content = True

    def __init__(self, app, request=None):
        """Store current request."""
        self.app = app
        self.request = request

    @property
    def dom_id(self):
        """The ``id`` tag of the panel's tab."""
        return 'pDebug%sPanel' % (self.name.replace(' ', ''))

    @property
    def title(self):
        """Provide a panel title."""
        return self.name

    @property
    def nav_title(self):
        """Provide a navigation title."""
        return self.title

    @staticmethod
    def wrap_handler(handler, context_switcher):
        """Wrap handler to additional logic layer."""
        return handler

    @asyncio.coroutine
    def process_response(self, response):
        """Process a response."""
        pass

    def render_content(self):
        """Render the panel's content."""
        if not self.has_content:
            return ""
        template = self.template
        if isinstance(self.template, str):
            template = self.app.ps.jinja2.env.get_template(self.template)
        context = self.render_vars()
        content = template.render(app=self.app, request=self.request, **context)
        return content

    @staticmethod
    def render_vars():
        """Provide template's context."""
        return {}


class HeaderDebugPanel(DebugPanel):

    """A panel to display HTTP request and response headers."""

    name = 'HTTP Headers'
    template = 'debugtoolbar/panels/headers.html'

    def __init__(self, app, request):
        """Store current requests headers."""
        super().__init__(app, request)
        self.request_headers = [(k, v) for k, v in sorted(request.headers.items())]
        self.response_headers = None

    @asyncio.coroutine
    def process_response(self, response):
        """Store response headers."""
        self.response_headers = [(k, v) for k, v in sorted(response.headers.items())]

    def render_vars(self):
        """Template context variables."""
        return dict(response_headers=self.response_headers, request_headers=self.request_headers)


class RoutesDebugPanel(DebugPanel):

    """A panel to display the routes used by your Muffin application."""

    name = 'Routes'
    template = 'debugtoolbar/panels/routes.html'

    def __init__(self, app, request=None):
        """Get routes."""
        super().__init__(app, request)
        self.routes = []
        router = app.router

        for route in router._urls:
            if not route.name or route.name.startswith('debugtoolbar.'):
                continue
            pattern = ''
            if isinstance(route, web.DynamicRoute):
                pattern = route._formatter
            elif isinstance(route, web.StaticRoute):
                pattern = route._prefix
            elif isinstance(route, web.PlainRoute):
                pattern = route._path

            self.routes.append({
                "name": route.name,
                "method": route.method,
                "pattern": pattern,
                "handler": repr(route.handler)
            })

    def render_vars(self):
        """Template Context."""
        return {'routes': self.routes}


class ConfigurationDebugPanel(DebugPanel):

    """Render app config."""

    name = 'Configuration'
    has_content = True
    template = 'debugtoolbar/panels/configuration.html'


class VersionsDebugPanel(DebugPanel):

    """Render python packages versions."""

    name = 'Versions'
    has_content = True
    template = 'debugtoolbar/panels/versions.html'

    def __init__(self, app, request=None):
        """Get environment meta information."""
        super(VersionsDebugPanel, self).__init__(app, request)
        self.platform = platform.platform()
        self.packages = []
        for distribution in pkg_resources.working_set:
            name = distribution.project_name
            dependencies = [d.project_name for d in distribution.requires()]

            # parse home page url
            metadata_file = distribution.PKG_INFO
            lines = distribution.get_metadata_lines(metadata_file)
            url = '#'
            for l in lines:
                if l.startswith('Home-page:'):
                    url = l[10:].strip()
                    break

            self.packages.append({
                'version': distribution.version,
                'lowername': name.lower(),
                'name': name,
                'dependencies': dependencies,
                'url': url})

        self.packages = sorted(self.packages, key=itemgetter('lowername'))

    def render_vars(self):
        """Provide template's context."""
        return {
            'platform': self.platform,
            'packages': self.packages,
            'muffin_version': muffin_version,
        }


class MiddlewaresDebugPanel(DebugPanel):

    """Information about enabled middlewares."""

    name = 'Middleware Factories'
    template = 'debugtoolbar/panels/middlewares.html'

    def __init__(self, app, request=None):
        """Initialize the panel."""
        super(MiddlewaresDebugPanel, self).__init__(app, request)
        self.middlewares = []
        for mf in reversed(app._middlewares):
            self.middlewares.append(mf.__repr__())

    def render_vars(self):
        """Provide template's context."""
        return {'middlewares': self.middlewares}


class RequestVarsDebugPanel(DebugPanel):
    name = 'Request Vars'
    template = 'debugtoolbar/panels/request_vars.html'

    @asyncio.coroutine
    def process_response(self, response):
        request = self.request
        yield from request.post()
        self.data = {
            'get': [(k, request.GET.getall(k)) for k in request.GET],
            'post': [(k, saferepr(v)) for k, v in request.POST.items()],
            'cookies': [(k, request.cookies.get(k)) for k in request.cookies],
            'session': [(k, saferepr(v)) for k, v in getattr(request, 'session', {}).items()],
            'attrs': [(k, v) for k, v in request.items()],
        }

    def render_vars(self):
        return self.data


class TracebackDebugPanel(DebugPanel):
    name = 'Traceback'
    template = 'debugtoolbar/panels/traceback.html'

    @property
    def has_content(self):
        return 'pdbt_tb' in self.request

    def render_vars(self):
        tb = self.request['pdbt_tb']
        exc = escape(tb.exception)
        summary = Traceback.render_summary(tb, include_title=False, request=self.request)
        token = self.request.app['debugtoolbar']['pdbt_token']
        app = self.request.app
        return {
            'evalex': app.ps.debugtoolbar.cfg.intercept_exc == 'debug' and 'true' or 'false',
            'console': 'false',
            'lodgeit_url': None,
            'title': exc,
            'exception': exc,
            'exception_type': escape(tb.exception_type),
            'summary': summary,
            'plaintext': tb.plaintext,
            'plaintext_cs': re.sub('-{2,}', '-', tb.plaintext),
            'traceback_id': tb.id,
            'token': token,
            'url': '',
            'static_path': app.ps.debugtoolbar.cfg.prefix + 'static/',
            'root_path': app.ps.debugtoolbar.cfg.prefix,
        }


class LoggingDebugPanel(DebugPanel):

    name = 'Logging'
    template = 'debugtoolbar/panels/logging.html'

    def __init__(self, app, request=None):
        super(LoggingDebugPanel, self).__init__(app, request)
        self.handler = LoggingTrackingHandler()

    @property
    def nav_title(self):
        """ Get a navigation title. """
        return "%s (%s) " % (self.title, len(self.handler.records))

    @property
    def has_content(self):
        return self.handler.records

    def wrap_handler(self, handler, context_switcher):
        context_switcher.add_context_in(lambda: logging.root.addHandler(self.handler))
        context_switcher.add_context_out(lambda: logging.root.removeHandler(self.handler))
        return handler

    def render_vars(self):
        return {
            'records': [
                {
                    'message': record.getMessage(),
                    'time': dt.datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                    'level': record.levelname,
                    'file': os.path.relpath(record.pathname),
                    'file_long': record.pathname,
                    'line': record.lineno,
                } for record in self.handler.records
            ]
        }


# pylama:ignore=W0212,W0201
