""" Debugtoolbar utils. """

from collections import OrderedDict


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
