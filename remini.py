#!/usr/bin/env python3

import logging
import os
from urllib.parse import unquote, urlparse
from datetime import datetime
from typing import List, Union, Tuple

import praw
from praw.models import Submission, Subreddit, Comment, Redditor

from md2gemini import md2gemini

# How to format dates and times
DATE_FMT = '%d/%m/%Y'
DATETIME_FMT = f'{DATE_FMT} at %H:%M UTC'

# How many items (comments, submissions, etc) to display
ITEM_LIMIT = 25

# Get certain config options from environment variables
try:
    BASE_URL = os.environ['REMINI_BASE_URL']
    PRAW_FILE = os.environ['REMINI_PRAW_FILE']
except KeyError:
    raise RuntimeError('Need to specify "REMINI_BASE_URL" and "REMINI_PRAW_FILE"'
                       ' environment variables.')

# If this environment variable is set, we will log to that file;
# otherwise, we just log to stderr.
LOG_FILE = os.environ.get('REMINI_LOG_FILE')
if LOG_FILE:
    logging.basicConfig(filename=LOG_FILE)

# If this environment variable is set, we will display the relevant
# file to the client when a request is received without any path info
# or query.
LANDING_PAGE = os.environ.get('REMINI_LANDING_PAGE')

# Error message to print when we don't know what happened.
GENERIC_ERR_MSG = ('Got unexpected error. This could include the page not being available, '
                   'Reddit being down, or some other error. Details of the error have been logged.')

with open(PRAW_FILE) as f:
    CLIENT_ID, CLIENT_SECRET, USER_AGENT = (line.strip() for line in f.readlines())

# The different bases for Reddit URLs
REDDIT_DOMAINS = [
    ['redd', 'it'],
    ['reddit', 'com']
]

# Top level Reddit "commands" that we support
REDDIT_CMDS = {
    'r',
    'u'
}

reddit = praw.Reddit(
    user_agent=USER_AGENT,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET
)

# General helper functions

## These functions act on PRAW objects to help us retrieve key information
## about them.

def date_time(obj: Union[Comment, Submission, Subreddit, Redditor], date_only: bool = False) -> str:
    """Get a properly-formatted string representing the date (and \
            optionally time) a PRAW object was created (in UTC).

    :param obj: The object whose date and time we want to display. It \
            should have a `created_utc` attribute which is the Unix \
            time representation of its creation time.
    :param date_only: Whether to display the full date and time of the \
            the object's creation, or just the date.

    :return: The formatted string. Format is determined by \
            `DATETIME_FMT` or `DATE_FMT`.

    """
    if date_only:
        fmt = DATE_FMT
    else:
        fmt = DATETIME_FMT
    s = datetime.utcfromtimestamp(obj.created_utc).strftime(fmt)
    try:
        if obj.edited:
            s += '*'
    except AttributeError:
        # obj cannot be edited (eg, Subreddit)
        pass
    return s

def author(obj: Union[Comment, Submission]) -> str:
    """Get the name of the author of an object, if possible.

    :param obj: The object whose name we are looking for. Should have \
            an `author` attribute which is an instance of \
            praw.models.Redditor.
    :return: The name of the author, or "[deleted]" if the name could \
            not be found.
    """

    try:
        return obj.author.name
    except AttributeError:
        return '[deleted]'

def get_submission_url(comment: Comment) -> str:
    """Get the URL of the submission to which a comment relates.

    :param: The praw.models.Comment object to inspect.
    :return: The (Remini-usable) URL of the submission.

    """
    return parse_reddit_url('/'.join(comment.permalink.rstrip('/').split('/')[:-1]))
    

def get_parent_url(comment: Comment) -> Tuple[str, bool]:
    """Get the URL of the parent of a Reddit comment (ie, the comment \
            or submission the comment is replying to). The URL will be \
            usable by Remini.

    :param comment: The praw.models.Comment objecti to inspect.
    :param parse: Whether to return the URL as a parsed, "Remini-\
            friendly" URL.
    :return: A tuple containing the URL of the parent comment or \
            submission and a bool indicating whether the parent is a \
            submission.

    """

    parent_id = comment.parent_id
    if parent_id.startswith('t1_'):
        # Parent is a comment. Take the URL of this comment and replace
        # the last bit (the comment ID) with the parent's ID.
        fragments = comment.permalink.rstrip('/').split('/')
        fragments[-1] = parent_id.lstrip('t1_')
        return parse_reddit_url('/'.join(fragments)), False
    elif parent_id.startswith('t3_'):
        # Parent is a submission. 
        return get_submission_url(comment), True
    else:
        raise ValueError(f'Bad ID "{parent_id}". Expecting it to start with t1_ or t3_.')


## These functions parse Reddit URLs or markdown to convert them to
## Remini-friendly equivalents.

def parse_reddit_url(url: str) -> str:
    """If a URL is for a page on Reddit, convert to a Remini URL; \
            otherwise, return the URL unchanged.
    
    :param url: The URL to convert.
    :return: The converted URL or the original URL, as applicable.
    
    """
    # NOTE: BASE_URL should end with a /, which means whatever we add to
    # BASE_URL should not begin with a /
    logging.debug(f'Parsing Reddit URL "{url}".')
    parsed = urlparse(url)
    if not (parsed.scheme or parsed.netloc):
        # URL appears to be relative
        reddit_url = True
    else:
        domain = parsed.netloc.split('.')[-2:]
        for d in REDDIT_DOMAINS:
            if d == domain:
                reddit_url = True
                break
        else:
            reddit_url = False
    if reddit_url and handle_request(parsed.path, parsed.query, True):
        logging.debug('URL is supported Reddit URL; converting.')
        new_url = BASE_URL + parsed.path.lstrip('/')
        logging.debug(f'New URL is "{new_url}".')
        return new_url
    else:
        logging.debug(f'URL is not Reddit URL; returning unchanged.')
        return url

def parse_markdown(md: str) -> List[str]:
    """Parse Reddit-style markdown, converting to gemtext and making
    some other adjustments.
    
    :param md: The Reddit-style markdown to parse.
    :return: The resulting gemtext as a list of line strings.

    """
    gemtext = md2gemini(md, links='paragraph').split('\n')
    for i, line in enumerate(gemtext):
        if line.startswith('#') or line.startswith('##'):
            gemtext[i] = '#' + line
        elif line.startswith('=> '):
            tokens = line.split(' ')
            tokens[1] = parse_reddit_url(tokens[1])
            gemtext[i] = ' '.join(tokens)
    return gemtext

## These functions are for sending responses to the client.

def ok(lines: List[str], join_on_newline: bool = True) -> bytes:
    """Send the given lines to stdout, preceded by a 20 (success) \
            response.

    :param lines: List of lines to send to stdout.
    :param join_on_newline: Whether to join `lines` on newlines, or an \
            empty string. Should be False if each line in `lines` \
            already has a newline at the end.
    :return: Bytes to be sent to the client.

    """
    if join_on_newline:
        content = '\n'.join(lines)
    else:
        content = ''.join(lines)

    return f'20 text/gemini\r\n{content}\n'.encode()

def bad_request(msg: str = '') -> bytes:
    """Send a 59 (bad request) response.
    
    :param msg: Error message to display to the user.
    :return: Bytes to be sent to the client.
    
    """
    return f'59 {msg}\r\n'.encode()

def get_input(msg: str = '') -> bytes:
    """Send a 10 (input) response.

    :param msg: Prompt to display to the user.
    :return: Bytes to be sent to the client.

    """
    return f'10 {msg}\r\n'.encode()

def redirect(url: str, perm: bool = True) -> bytes:
    """Send a 3x (redirect) response.

    :param url: The URL to redirect to.
    :param perm: Whether this is a permanent redirect.
    :return: Bytes to be sent to the client.

    """
    code = 31 if perm else 30
    return f'{code} {url}\r\n'.encode()


# Functions for displaying a subreddit

def display_subreddit(name: str, sortby: str = 'hot', limit: int = 10) -> List[str]:
    """Get a list of submissions for a given subreddit.

    :param name: The name of the subreddit.
    :param sortby: How to sort submissions ('top', 'hot', 'new' or \
            'controversial').
    :param limit: How many submissions to display.
    :return: A list of line strings to be displayed to the user.

    """
    subreddit = reddit.subreddit(name)
    timestamp = date_time(subreddit, date_only=True)

    lines = [
        f'# Subreddit: {subreddit.display_name}',
        f'Created on {timestamp}. {subreddit.subscribers} subscribers.',
        '',
        '## Submissions'
        ''
    ]
    if sortby == 'hot':
        submissions = subreddit.hot(limit=ITEM_LIMIT)
    elif sortby == 'top':
        submissions = subreddit.top(limit=ITEM_LIMIT)
    elif sortby == 'new':
        submissions = subreddit.new(limit=ITEM_LIMIT)
    elif sortby == 'controversial':
        submissions = subreddit.controversial(limit=ITEM_LIMIT)
    else:
        raise ValueError(f'Bad value for sortby: "{sortby}".')

    if not submissions:
        lines.append('There\'s nothing here!')

    for s in submissions:
        lines.extend(submission_summary(s))
        lines.append('')

    return lines

def submission_summary(submission: Submission) -> List[str]:
    """Display a summary of a submission (such as if we are viewing a \
            list of submissions from the subreddit page).

    :param submission: The praw.models.Submission object we want to \
            display.
    :return: A list of strings, which will be displayed to the user as \
            lines, in order.

    """

    lines = []
    
    url = parse_reddit_url(submission.url)
    lines.append(f'=> {url} {submission.title}')
    
    author_name = author(submission)
    timestamp = date_time(submission)
    upvotes = submission.score
    parsed = urlparse(submission.url)
    scheme = parsed.scheme
    netloc = parsed.netloc
    lines.append(f'created by {author_name} on {timestamp} - {submission.score} upvotes ({scheme}, {netloc})')

    comments_url = parse_reddit_url(submission.permalink)
    lines.append(f'=> {comments_url} {submission.num_comments} comments')

    return lines


# Functions for displaying a submission and comments

def display_submission(submission_id: str) -> List[str]:
    """Display the permalink for a submission. Displays the body (if \
            any) of the submission at the top of the page followed by \
            a list of the direct replies.

    :param submission_id: The ID of the submission we want to display.
    :return: A list of strings, which will be displayed to the user as \
            lines, in order.

    """
    submission = reddit.submission(id=submission_id)
    timestamp = date_time(submission)
    comments = submission.comments[:ITEM_LIMIT]

    total_comments = len(submission.comments)
    showing_comments = len(comments)

    lines = [
        f'# {submission.title}',
        f'=> {submission.url}',
        f'created by {author(submission)} on {timestamp}',
        f'{submission.score} upvotes, {total_comments} top-level comments (showing {showing_comments})',
        '',
    ]

    if submission.selftext:
        lines.extend([
            *parse_markdown(submission.selftext),
            ''
        ])

    lines.extend([
        '',
        '# Comments',
        ''
    ])

    if not comments:
        lines.append('There\'s nothing here!')
    else:
        for c in comments:
            lines.extend(comment_summary(c, show_num_replies=True))
            lines.append('')

    return lines

def display_comment(comment_id: str) -> List[str]:
    """Display the permalink for a comment. Displays the body of the \
            comment at the top of the page followed by a list of the \
            direct replies.

    :param comment_id: The ID of the comment we want to display.
    :return: A list of strings, which will be displayed to the user as \
            lines, in order.

    """
    comment = reddit.comment(id=comment_id)
    # Apparently need to do this refresh to get replies if the comment
    # is not from a submission
    comment.refresh()
    author_name = author(comment)
    timestamp = date_time(comment)
    body = parse_markdown(comment.body)

    replies = comment.replies[:ITEM_LIMIT]
    total_replies = len(comment.replies)
    showing_replies = len(replies)

    lines = [
        f'# Comment by {author_name} on {timestamp}',
        f'{comment.score} upvotes, {total_replies} direct replies (showing {showing_replies})',
        f'=> {get_submission_url(comment)} View submission: {comment.submission.title}'
    ]
    parent_url, is_submission = get_parent_url(comment)
    if not is_submission:
        lines.append(f'=> {parent_url} View parent comment')
    
    lines.extend([
        '',
        *body,
        '',
        '',
        '# Replies',
        ''
    ])

    if not replies:
        lines.append('There\'s nothing here!')
    else:
        for c in replies:
            lines.extend(comment_summary(c, show_num_replies=True))
            lines.append('')

    return lines


def comment_summary(comment: Comment, show_num_replies: bool = False) -> List[str]:
    """Display a summary of a comment (such as if we are viewing a \
            list of comments on a submission page).

    :param comment: The praw.models.Comment object we want to display.
    :param show_num_comments: Whether to display the number of direct \
            replies the comment has received. Replies will only be \
            available (without many expensive refresh() calls) if the \
            comment is a child of a submission.
    :return: A list of strings, which will be displayed to the user as \
            lines, in order.

    """

    author_name = author(comment)
    timestamp = date_time(comment)
    body = parse_markdown(comment.body)
    url = parse_reddit_url(comment.permalink)

    metadata = f'{comment.score} upvotes'
    if show_num_replies:
        metadata += f', {len(comment.replies)} direct replies'

    return [
        f'=> {url} Comment by {author_name} at {timestamp}',
        metadata,
        '',
        *body
    ]


# Functions for displaying a user profile

def display_redditor(name: str) -> List[str]:
    """Display a Reddit user's submissions.

    :param name: The name of the user we want to display.
    :return: A list of strings, which will be displayed to the user as \
            lines, in order.

    """
    redditor = reddit.redditor(name)

    lines = [
        f'# Redditor: {redditor.name}',
    ]

    try:
        if redditor.is_suspended:
            lines.append('User is banned or suspended.')
            return lines
    except AttributeError:
        pass

    timestamp = date_time(redditor, date_only=True)
    lines.extend([ 
        f'Redditor since {timestamp} ({redditor.link_karma} link karma, {redditor.comment_karma} comment karma)',
        ''
    ])

    lines.append('# Submissions')
    lines.append('')
    submissions = redditor.submissions.new(limit=ITEM_LIMIT)
    if submissions:
        for s in submissions:
            lines.extend(submission_summary(s))
            lines.append('')
    else:
        lines.append('User has no submissions.')
        lines.append('')

    lines.append('# Comments')
    lines.append('')
    comments = redditor.comments.new(limit=ITEM_LIMIT)
    if comments:
        for c in comments:
            lines.extend(comment_summary(c))
            lines.append('')
    else:
        lines.append('User has no comments.')
        lines.append('')

    return lines
 

# Tying it all together

def handle_r(tokens: List[str], path: str, query: str, check_only: bool = False) -> Union[bytes, bool]:
    """Process a request where the path begins with "/r/".
    
    :param tokens: A list of strings, each representing a fragment of \
            the request path (the leading 'r' is removed).
    :param path: The full request path. Helpful for logging.
    :param query: The query string (ie, the bit of the URL following \
            a "?", if any).
    :param check_only: If True, rather than returning data to send to \
            the client, simply return True or False based on whether \
            the path is supported. Use to check whether we need to \
            convert Reddit URLs.

    :return: A bytes object containing the response to be sent to the \
            client, or, if ``check_only`` is True, a bool representing \
            whether the path is supported.
    
    """
    
    if (len(tokens) >= 5) and (tokens[1] == 'comments'):
        # Request is for a specific comment
        comment_id = tokens[4]
        if check_only:
            return True
        logging.debug(f'Displaying comment with ID "{comment_id}".')
        return ok(display_comment(comment_id))
    elif (len(tokens) >= 3) and (tokens[1] == 'comments'):
        # Request is for all comments for a submission
        submission_id = tokens[2]
        if check_only:
            return True
        logging.debug(f'Displaying submission with ID "{submission_id}".')
        return ok(display_submission(submission_id))
    elif len(tokens) == 1:
        # Request is to display subreddit
        name = tokens[0]
        if check_only:
            return True
        logging.debug(f'Displaying subreddit with name "{name}".')
        return ok(display_subreddit(name))
    elif tokens:
        # Got some unexpected form of URL. Log an error and return a bad request response
        if check_only:
            return False
        logging.error(f'Got unexpected set of tokens: {tokens}.')
        return bad_request(f'Request invalid or not supported: {path}')
    else:
        if check_only:
            return True
        if query:
            redirect_to = f'{BASE_URL}r/{query}'
            logging.debug(f'No path, but query found - redirecting to "{redirect_to}".')
            return redirect(redirect_to)
        else:
            logging.debug('No path or query found - prompting for subreddit name.')
            return get_input('Enter subreddit name:')

def handle_u(tokens: List[str], path: str, query: str, check_only: bool = False) -> Union[bytes, bool]:
    """Process a request where the path begins with "/u/".

    :param tokens: A list of strings, each representing a fragment of \
            the request path (the leading 'u' is removed).
    :param path: The full request path. Helpful for logging.
    :param query: The query string (ie, the bit of the URL following \
            a "?", if any).
    :param check_only: If True, rather than returning data to send to \
            the client, simply return True or False based on whether \
            the path is supported. Use to check whether we need to \
            convert Reddit URLs.

    :return: A bytes object containing the response to be sent to the \
            client, or, if ``check_only`` is True, a bool representing \
            whether the path is supported.

    """

    if tokens:
        if len(tokens) == 1:
            if check_only:
                return True
            name = tokens[0]
            logging.debug(f'Displaying user profile for {name}.')
            return ok(display_redditor(name))
        else:
            if check_only:
                return False
            logging.warning(f'Got unsupported path "{path}".')
            return bad_request(f'Request invalid or not supported: {path}')
    else:
        if check_only:
            return True
        if query:
            redirect_to = f'{BASE_URL}u/{query}'
            logging.debug(f'No path, but query found - redirecting to "{redirect_to}".')
            return redirect(redirect_to)
        else:
            logging.debug('No path or query found - prompting for Redditor name.')
            return get_input('Enter Redditor name:')

def handle_request(path: str, query: str = '', check_only: bool = False) -> Union[bytes, bool]:
    """Handle a single request.
    
    :param path: The request path (ie, the bit of the URL following \
            the script endpoint and before a "?").
    :param query: The query string (ie, the bit of the URL following \
            a "?", if any).
    :param check_only: If True, rather than returning data to send to \
            the client, simply return True or False based on whether \
            the path is supported. Use to check whether we need to \
            convert Reddit URLs.

    :return: A bytes object containing the response to be sent to the \
            client, or, if ``check_only`` is True, a bool representing \
            whether the path is supported.

    """
    path = path.strip().strip('/')
    if not path:
        # No additional path has been included.
        logging.debug('Empty path received.')
        if check_only:
            return True
        if LANDING_PAGE:
            with open(LANDING_PAGE) as f:
                return ok(f.readlines(), join_on_newline=False)
        else:
            return ok(['Remini is working, but no landing page has been set.'])
    if check_only:
        logging.debug(f'Checking support for path "{path}".')
    else:
        logging.debug(f'Resolving path "{path}".')
    tokens = unquote(path).split('/')
    if not tokens[0]:
        # If the path we receive starts with a "/", the first item of this list
        # will be an empty string, so we remove that.
        tokens = tokens[1:]
    if not tokens[-1]:
        # Last token is empty string, meaning path ended with /
        tokens.pop()
    #logging.debug(f'Tokens: {tokens}')
    cmd = tokens[0]
    logging.info(f'Got command "{cmd}".')
    if cmd == 'r':
        return handle_r(tokens[1:], path, query, check_only)
    elif cmd == 'u':
        return handle_u(tokens[1:], path, query, check_only)
    else:
        if check_only:
            logging.debug(f'Path not supported: Unknown comment "{cmd}".')
            return False
        else:
            logging.error(f'Unknown command "{cmd}".')
            return bad_request(f'Couldn\'t parse path "{path}".')


def from_cmd_line():
    full_path = sys.argv[-1]
    parsed = urlparse(full_path)
    path = parsed.path
    query = parsed.query
    try:
        print(handle_request(path, query).decode())
    except Exception as e:
        logging.error(e, exc_info=True)
        print(bad_request(GENERIC_ERR_MSG))

def from_scgi():
    
    import socket
    import scgi.scgi_server

    try:
        SOCK = os.environ['REMINI_SCGI_SOCK']
    except KeyError:
        raise RuntimeError('Must set "REMINI_SCGI_SOCK" environment variable.')
    if os.path.exists(SOCK):
        os.remove(SOCK)
    
    class ReminiHandler(scgi.scgi_server.SCGIHandler):

        def produce(self, env, bodysize, input, output):
            path = env.get('PATH_INFO')
            logging.debug(f'PATH_INFO is "{path}".')
            query = env.get('QUERY_STRING')
            logging.debug(f'QUERY_STRING is "{query}".')
            try:
                output.write(handle_request(path, query))
            except Exception as e:
                # Catch-all for any unhandled exception
                logging.error(e, exc_info=True)
                output.write(bad_request(GENERIC_ERR_MSG))
    
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(SOCK)
    server = scgi.scgi_server.SCGIServer(handler_class=ReminiHandler)
    server.serve_on_socket(s)

if __name__ == '__main__':

    import sys

    if '--debug' in sys.argv:
        logging.getLogger().setLevel(logging.DEBUG)

    if '--cli' in sys.argv:
        # Run from command line, not SCGI
        from_cmd_line()
    else:
        from_scgi()

