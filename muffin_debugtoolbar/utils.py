""" Debugtoolbar utils. """

import logging
import sys
from collections import OrderedDict, deque


class History(OrderedDict):

    """ OrderedDict with size. """

    def __init__(self, size=100):
        """ Save size. """
        self.size = size
        super(History, self).__init__()

    def __setitem__(self, *args, **kwargs):
        """ Cut if needed. """
        super(History, self).__setitem__(*args, **kwargs)
        if len(self) > self.size:
            self.popitem(False)


class LoggingTrackingHandler(logging.Handler):

    def __init__(self, *args, **kwargs):
        super(LoggingTrackingHandler, self).__init__(*args, **kwargs)
        self.records = deque(maxlen=100)

    def emit(self, record):
        self.records.append(record)


class ContextSwitcher:
    """This object is alternative to *yield from*. It is useful in cases
    when you need to track context switches inside coroutine.

    see: https://www.python.org/dev/peps/pep-0380/#formal-semantics
    """
    def __init__(self):
        self._on_context_switch_out = []
        self._on_context_switch_in = []

    def add_context_in(self, callback):
        assert callable(callback), 'callback should be callable'
        self._on_context_switch_in.append(callback)

    def add_context_out(self, callback):
        assert callable(callback), 'callback should be callable'
        self._on_context_switch_out.append(callback)

    def __call__(self, expr):
        for callbale in self._on_context_switch_in:
            callbale()

        _i = iter(expr)
        try:
            _y = next(_i)
        except StopIteration as _e:
            _r = _e.value
        else:
            while 1:
                try:
                    for callbale in self._on_context_switch_out:
                        callbale()
                    _s = yield _y
                    for callbale in self._on_context_switch_in:
                        callbale()
                except GeneratorExit as _e:
                    try:
                        _m = _i.close
                    except AttributeError:
                        pass
                    else:
                        _m()
                    raise _e
                except BaseException as _e:
                    _x = sys.exc_info()
                    try:
                        _m = _i.throw
                    except AttributeError:
                        raise _e
                    else:
                        try:
                            _y = _m(*_x)
                        except StopIteration as _e:
                            _r = _e.value
                            break
                else:
                    try:
                        if _s is None:
                            _y = next(_i)
                        else:
                            _y = _i.send(_s)
                    except StopIteration as _e:
                        _r = _e.value
                        break
        result = _r
        for callbale in self._on_context_switch_out:
            callbale()
        return result
