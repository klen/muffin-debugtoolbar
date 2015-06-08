import muffin
import pytest


@pytest.fixture(scope='session')
def app(loop):
    app = muffin.Application(
        'debug', loop=loop,

        PLUGINS=['muffin_jinja2', 'muffin_debugtoolbar'],
    )

    @app.register('/')
    def index(request):
        return '<body>Hello, World!</body>'

    return app


def test_debugtoolbar(client):
    response = client.get('/')
    assert "DebugToolbar" in response.text

    response = client.get('/_debug')
    assert 'History' in response.text
    assert 'Global' in response.text
