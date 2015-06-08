""" Example application for Debug toolbar. """

import muffin


app = muffin.Application(
    'debug',

    PLUGINS=(
        'muffin_jinja2',
        'muffin_debugtoolbar',
    ))

from example.views import *  # noqa
