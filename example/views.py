from example import app, muffin


@app.register('/')
def index(request):
    """ Just sample. """
    return (
        "<body>"
        "Hello, World!"
        "<ul>"
        "<li><a href='/_debug'>Debug Toolbar</a></li>"
        "<li><a href='/redirect'>Redirect</a></li>"
        "<li><a href='/exception'>Exception</a></li>"
        "</ul>"
        "</body>"
    )


@app.register('/redirect')
def redirect(request):
    """ Just sample. """
    raise muffin.HTTPFound('/')


@app.register('/exception')
def exception(request):
    return 1 / 0
