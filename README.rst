==============================
Remini - a Gemini/Reddit proxy
==============================

Remini is a proxy service that allows some basic browsing of `Reddit <https://www.reddit.com>`_ from `Geminispace <https://gemini.circumlunar.space>`_.

It is a work in progress. Currently supported features are:

* Viewing a user's recent comments and submissions.
* Viewing a subreddit's "hot" submissions.
* Viewing a submission's top comments.
* Viewing the top replies to a comment.

Dependencies
============

Remini is a Python script and requires Python 3.6 or later. It also depends on the ``praw``, ``scgi`` and ``md2gemini`` Python libraries.

Because Remini serves requests using `SCGI <https://en.wikipedia.org/wiki/Simple_Common_Gateway_Interface>`_, you'll need to be running a Gemini server that supports SCGI. `Molly Brown <https://tildegit.org/solderpunk/molly-brown>`_ is a popular example.

Installation
============

I haven't yet packaged Remini, so to get it, just clone this repository:

``git clone git@github.com:bunburya/remini.git``

The ``remini.py`` file is the one you want.

Configuration and running
=========================

First, you'll need to configure your server to pass relevant requests to a Unix socket file using the SCGI protocol. Consult the documentation for your chosen server for details on how to do this.

Remini uses `PRAW <https://praw.readthedocs.io/en/latest/>`_ to access Reddit's API. You don't need to provide a Reddit username or password, but you do need to provide a client ID and a client secret (and obtaining these requires a Reddit account). See `this page <https://github.com/reddit-archive/reddit/wiki/OAuth2-Quick-Start-Example#first-steps>`_ for instructions on how to obtain a client ID and client secret. You should then create a text file with the following data, each on its own line (and nothing else):

#. your client ID;
#. your client secret; and
#. the user agent that Remini should used when querying the Reddit API (see `Reddit's API rules <https://github.com/reddit-archive/reddit/wiki/API>`_ for information on what is a good user agent).

Remini requires the following environment variables to be set when running:

* ``REMINI_BASE_URL``: The base of all requests to Remini. For example, if you want a request to your Remini service to look something like ``gemini://gemini.example.org/remini/r/geminiprotocol`` (to view the /r/geminiprotocol subreddit), your ``REMINI_BASE_URL`` would be ``gemini://gemini.example.org/remini/`` (note the trailing ``/``). Obviously, this should be consistent with the URL you have specified in your server's SCGI configuration.
* ``REMINI_PRAW_FILE``: The path to the file you created with your PRAW information.
* ``REMINI_SCGI_SOCK``: The path to the Unix socket file that your server will pass the SCGI request to.

The following environment variables can optionally be set:

* ``REMINI_LANDING_PAGE``: A path to a "landing page" to be displayed when a client requests your base URL without any additional information. If not provided, some very short, generic message will be displayed instead.
* ``REMINI_LOG_FILE``: The path to the file to which Remini should write its logs. If not provided, Remini will log to standard error.

Note that certain other aspects of Remini's behaviour can be configured by changing variables in the ``remini.py`` script. The ones you might want to change usually have names in ALL_CAPS.

Once all that is done, you can just run the ``remini.py`` script. Running it with the ``--debug`` flag will increase the verbosity of logging. If you provide a ``--cli`` argument followed by a path (eg, ``remini.py --cli r/geminiprotocol``), Remini will not serve requests over SCGI, but rather print the output of a single request to standard output and then exit. This can also be helpful for debugging.

You can use your operating system's init system, such as `systemd <https://en.wikipedia.org/wiki/Systemd>`_ to run Remini as a daemon. Included in the repo is a sample ``remini.service`` file that you can use to launch Remini via systemd.

How it works
============

Just append the path of the Reddit URL (after the domain name) to your base URL. For example, assuming your base URL is ``gemini://gemini.example.org/remini/``:

* ``gemini://gemini.example.org/remini/r/geminiprotocol`` will display the `/r/geminiprotocol <https://www.reddit.com/r/geminiprotocol/>`_ subreddit.
* ``gemini://gemini.example.org/remini/u/spez`` will display the Redditor `/u/spez <https://www.reddit.com/user/spez>`_.
* ``gemini://gemini.example.org/remini/r/coding/comments/hl6qfv/a_look_at_the_gemini_protocol_a_brutally_simple/`` will display the comments for the `relevant submission <https://www.reddit.com/r/coding/comments/hl6qfv/a_look_at_the_gemini_protocol_a_brutally_simple/>`_.


