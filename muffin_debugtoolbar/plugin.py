"""Debug Toolbar Plugin."""
import asyncio
import importlib
import ipaddress as ip
import os.path as op
import re
import sys
import uuid

from muffin import (
    Response, StaticRoute, HTTPException, HTTPBadRequest, to_coroutine, HTTPForbidden)
from muffin.plugins import BasePlugin, PluginException
from muffin.utils import json

from . import panels, utils
from .tbtools.tbtools import get_traceback


RE_BODY = re.compile(b'<\/body>', re.I)
U_SSE_PAYLOAD = "id: {0}\nevent: new_request\ndata: {1}\n\n"
REDIRECT_CODES = (300, 301, 302, 303, 305, 307, 308)


PLUGIN_ROOT = op.dirname(op.abspath(__file__))


@asyncio.coroutine
def debugtoolbar_middleware_factory(app, handler):
    """Setup Debug middleware."""
    dbtb = app.ps.debugtoolbar

    @asyncio.coroutine
    def debugtoolbar_middleware(request):
        """Integrate to application."""

        # Check for debugtoolbar is enabled for the request
        if not dbtb.cfg.enabled or any(map(request.path.startswith, dbtb.cfg.exclude)):
            return (yield from handler(request))

        remote_host, remote_port = request.transport.get_extra_info('peername')
        for host in dbtb.cfg.hosts:
            if ip.ip_address(remote_host) in ip.ip_network(host):
                break
        else:
            return (yield from handler(request))

        # Initialize a debugstate for the request
        state = DebugState(app, request)
        dbtb.history[state.id] = state
        context_switcher = state.wrap_handler(handler)

        # Make response
        try:
            response = yield from context_switcher(handler(request))
            state.status = response.status
        except HTTPException as exc:
            response = exc
            state.status = response.status

        except Exception as exc:
            # Store traceback for unhandled exception
            state.status = 500
            if not dbtb.cfg.intercept_exc:
                raise
            tb = get_traceback(
                info=sys.exc_info(), skip=1, show_hidden_frames=False,
                ignore_system_exceptions=True, exc=exc)
            dbtb.exceptions[tb.id] = request['pdbt_tb'] = tb
            for frame in tb.frames:
                dbtb.frames[id(frame)] = frame
            response = Response(text=tb.render_full(request), content_type='text/html')

        # Intercept http redirect codes and display an html page with a link to the target.
        if dbtb.cfg.intercept_redirects and response.status in REDIRECT_CODES \
                and 'Location' in response.headers:

            response = yield from app.ps.jinja2.render(
                'debugtoolbar/redirect.html', response=response)
            response = Response(text=response, content_type='text/html')

        yield from state.process_response(response)

        if isinstance(response, Response) and response.content_type == 'text/html' and \
                RE_BODY.search(response.body):
            return (yield from dbtb.inject(state, response))

        return response

    return debugtoolbar_middleware


class Plugin(BasePlugin):

    """The plugin implementation."""

    name = 'debugtoolbar'
    defaults = {
        'enabled': True,
        'hosts': ['127.0.0.1'],
        'prefix': '/_debug',
        'intercept_exc': 'debug',  # debug/display/False,
        'intercept_redirects': True,
        'exclude': [],
        'panels': [
            panels.HeaderDebugPanel,
            panels.RequestVarsDebugPanel,
            panels.LoggingDebugPanel,
            panels.TracebackDebugPanel,
        ],
        'additional_panels': [],
        'global_panels': [
            panels.RoutesDebugPanel,
            panels.ConfigurationDebugPanel,
            panels.MiddlewaresDebugPanel,
            panels.VersionsDebugPanel,
        ]
    }

    def setup(self, app):
        """Setup the plugin and prepare application."""
        super(Plugin, self).setup(app)

        if 'jinja2' not in app.plugins:
            raise PluginException('The plugin requires Muffin-Jinja2 plugin installed.')

        self.cfg.prefix = self.cfg.prefix.rstrip('/') + '/'
        self.cfg.exclude.append(self.cfg.prefix)

        # Setup debugtoolbar templates
        app.ps.jinja2.cfg.template_folders.append(op.join(PLUGIN_ROOT, 'templates'))

        self.cfg.panels += list(self.cfg.additional_panels)
        panels_ = []
        for panel in self.cfg.panels:
            if isinstance(panel, str):
                mod, _, panel = panel.partition(':')
                mod = importlib.import_module(mod)
                panel = eval(panel or 'DebugPanel', mod.__dict__)
            panels_.append(panel)
        self.cfg.panels = panels_

        # Setup debugtoolbar static files
        app.router.register_route(StaticRoute(
            'debugtoolbar.static',
            self.cfg.prefix + 'static/',
            op.join(PLUGIN_ROOT, 'static')))

        app.register(self.cfg.prefix + 'sse', name='debugtoolbar.sse')(self.sse)
        app.register(
            self.cfg.prefix + 'exception', name='debugtoolbar.exception')(self.exception)
        app.register(
            self.cfg.prefix + 'execute', name='debugtoolbar.execute')(self.execute)
        app.register(
            self.cfg.prefix + 'source', name='debugtoolbar.source')(self.source)
        app.register(
            self.cfg.prefix.rstrip('/'),
            self.cfg.prefix,
            self.cfg.prefix + '{request_id}', name='debugtoolbar.request')(self.view)

        app['debugtoolbar'] = {}
        app['debugtoolbar']['pdbt_token'] = uuid.uuid4().hex
        self.history = app['debugtoolbar']['history'] = utils.History(50)
        self.exceptions = app['debugtoolbar']['exceptions'] = utils.History(50)
        self.frames = app['debugtoolbar']['frames'] = utils.History(100)

    @asyncio.coroutine
    def start(self, app):
        """ Start application. """
        app.middlewares.insert(0, debugtoolbar_middleware_factory)
        self.global_panels = [Panel(self.app) for Panel in self.cfg.global_panels]

    @asyncio.coroutine
    def inject(self, state, response):
        """ Inject Debug Toolbar code to response body. """
        html = yield from self.app.ps.jinja2.render(
            'debugtoolbar/inject.html',
            static_path=self.cfg.prefix + 'static',
            toolbar_url=self.cfg.prefix + state.id,
        )
        html = html.encode(state.request.charset or 'utf-8')
        response.body = RE_BODY.sub(html + b'</body>', response.body)
        return response

    @asyncio.coroutine
    def view(self, request):
        """ Debug Toolbar. """
        auth = yield from self.authorize(request)
        if not auth:
            raise HTTPForbidden()

        request_id = request.match_info.get('request_id')
        state = self.history.get(request_id, None)

        response = yield from self.app.ps.jinja2.render(
            'debugtoolbar/toolbar.html',
            debugtoolbar=self,
            state=state,
            static_path=self.cfg.prefix + 'static',
            panels=state and state.panels or [],
            global_panels=self.global_panels,
            request=state and state.request or None,
        )
        return Response(text=response, content_type='text/html')

    @asyncio.coroutine
    def authorize(self, request):  # noqa
        """Default authorization."""
        return True

    def authorization(self, func):
        """Define a authorization handler.

        ::
            debugtoolbar = muffin_debugtoolbar.Plugin()
            debugtoolbar.setup(app)

            @debugtoolbar.authorization
            def current_user_is_logged(request):
                user = yield from load_session(request)
                return user

        """
        self.authorize = to_coroutine(func)
        return func

    @asyncio.coroutine
    def sse(self, request):
        """SSE."""
        response = Response(status=200)
        response.content_type = 'text/event-stream'
        response.text = ''
        active_request_id = request.GET.get('request_id')
        client_last_request_id = str(request.headers.get('Last-Event-Id', 0))
        if self.history:
            last_request_id = next(reversed(self.history))
            if not last_request_id == client_last_request_id:
                data = []
                for _id in reversed(self.history):
                    data.append([
                        _id, self.history[_id].json, 'active' if active_request_id == _id else ''])
                if data:
                    response.text = U_SSE_PAYLOAD.format(last_request_id, json.dumps(data))

        return response

    def validate_pdtb_token(self, request):
        token = request.GET.get('token')

        if self.exceptions is None:
            raise HTTPBadRequest(text='No exception history')

        if not token:
            raise HTTPBadRequest(text='No token in request')

        if token != request.app['debugtoolbar']['pdbt_token']:
            raise HTTPBadRequest(text='Bad token in request')

    def get_frame(self, request):
        frame = int(request.GET.get('frm'), 0)
        if not frame or frame not in self.frames:
            return HTTPBadRequest()
        return self.frames[frame]

    @asyncio.coroutine
    def exception(self, request):
        self.validate_pdtb_token(request)
        tb = int(request.GET.get('tb', 0))
        if not tb or tb not in self.exceptions:
            raise HTTPBadRequest()
        tb = self.exceptions[tb]
        return Response(text=tb.render_full(request), content_type='text/html')

    @asyncio.coroutine
    def execute(self, request):
        self.validate_pdtb_token(request)
        if not self.cfg.intercept_exc == 'debug':
            raise HTTPBadRequest()
        cmd = request.GET.get('cmd')
        if not cmd:
            raise HTTPBadRequest()
        frame = self.get_frame(request)
        result = frame.console.eval(cmd)
        return Response(text=result, content_type='text/html')

    @asyncio.coroutine
    def source(self, request):
        self.validate_pdtb_token(request)
        frame = self.get_frame(request)
        return Response(text=frame.render_source(), content_type='text/html')


class DebugState:

    """ Store debug state. """

    def __init__(self, app, request):
        """Store the params."""
        self.request = request
        self.status = 200
        self.panels = [Panel(app, request) for Panel in app.ps.debugtoolbar.cfg.panels]

    @property
    def id(self):
        """Return state ID."""
        return str(id(self))

    @property
    def json(self):
        """Return JSON."""
        return {'method': self.request.method,
                'path': self.request.path,
                'scheme': 'http',
                'status_code': self.status}

    def wrap_handler(self, handler):
        context_switcher = utils.ContextSwitcher()
        for panel in self.panels:
            panel.wrap_handler(handler, context_switcher)
        return context_switcher

    @asyncio.coroutine
    def process_response(self, response):
        """Process response."""
        for panel in self.panels:
            yield from panel.process_response(response)
