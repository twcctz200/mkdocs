"""
Standalone file utils.

Nothing in this module should have an knowledge of config or the layout
and structure of the site and pages in the site.
"""
from __future__ import annotations

import functools
import logging
import os
import posixpath
import re
import shutil
import sys
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import PurePath
from typing import IO, TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

if sys.version_info >= (3, 10):
    from importlib.metadata import EntryPoint, entry_points
else:
    from importlib_metadata import EntryPoint, entry_points

import yaml
from mergedeep import merge
from yaml_env_tag import construct_env_tag

from mkdocs import exceptions

if TYPE_CHECKING:
    from mkdocs.structure.pages import Page

log = logging.getLogger(__name__)

markdown_extensions = (
    '.markdown',
    '.mdown',
    '.mkdn',
    '.mkd',
    '.md',
)


def get_yaml_loader(loader=yaml.Loader):
    """Wrap PyYaml's loader so we can extend it to suit our needs."""

    class Loader(loader):
        """
        Define a custom loader derived from the global loader to leave the
        global loader unaltered.
        """

    # Attach Environment Variable constructor.
    # See https://github.com/waylan/pyyaml-env-tag
    Loader.add_constructor('!ENV', construct_env_tag)

    return Loader


def yaml_load(source: IO, loader=None) -> Optional[Dict[str, Any]]:
    """Return dict of source YAML file using loader, recursively deep merging inherited parent."""
    Loader = loader or get_yaml_loader()
    result = yaml.load(source, Loader=Loader)
    if result is not None and 'INHERIT' in result:
        relpath = result.pop('INHERIT')
        abspath = os.path.normpath(os.path.join(os.path.dirname(source.name), relpath))
        if not os.path.exists(abspath):
            raise exceptions.ConfigurationError(
                f"Inherited config file '{relpath}' does not exist at '{abspath}'."
            )
        log.debug(f"Loading inherited configuration file: {abspath}")
        with open(abspath, 'rb') as fd:
            parent = yaml_load(fd, Loader)
        result = merge(parent, result)
    return result


def modified_time(file_path):
    warnings.warn(
        "modified_time is never used in MkDocs and will be removed soon.", DeprecationWarning
    )
    if os.path.exists(file_path):
        return os.path.getmtime(file_path)
    else:
        return 0.0


def get_build_timestamp() -> int:
    """
    Returns the number of seconds since the epoch.

    Support SOURCE_DATE_EPOCH environment variable for reproducible builds.
    See https://reproducible-builds.org/specs/source-date-epoch/
    """
    source_date_epoch = os.environ.get('SOURCE_DATE_EPOCH')
    if source_date_epoch is None:
        return int(datetime.now(timezone.utc).timestamp())

    return int(source_date_epoch)


def get_build_datetime() -> datetime:
    """
    Returns an aware datetime object.

    Support SOURCE_DATE_EPOCH environment variable for reproducible builds.
    See https://reproducible-builds.org/specs/source-date-epoch/
    """
    source_date_epoch = os.environ.get('SOURCE_DATE_EPOCH')
    if source_date_epoch is None:
        return datetime.now(timezone.utc)

    return datetime.fromtimestamp(int(source_date_epoch), timezone.utc)


def get_build_date() -> str:
    """
    Returns the displayable date string.

    Support SOURCE_DATE_EPOCH environment variable for reproducible builds.
    See https://reproducible-builds.org/specs/source-date-epoch/
    """
    return get_build_datetime().strftime('%Y-%m-%d')


def reduce_list(data_set: Iterable[str]) -> List[str]:
    """Reduce duplicate items in a list and preserve order"""
    return list(dict.fromkeys(data_set))


def copy_file(source_path: str, output_path: str) -> None:
    """
    Copy source_path to output_path, making sure any parent directories exist.

    The output_path may be a directory.
    """
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    if os.path.isdir(output_path):
        output_path = os.path.join(output_path, os.path.basename(source_path))
    shutil.copyfile(source_path, output_path)


def write_file(content: bytes, output_path: str) -> None:
    """
    Write content to output_path, making sure any parent directories exist.
    """
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(content)


def clean_directory(directory: str) -> None:
    """
    Remove the content of a directory recursively but not the directory itself.
    """
    if not os.path.exists(directory):
        return

    for entry in os.listdir(directory):
        # Don't remove hidden files from the directory. We never copy files
        # that are hidden, so we shouldn't delete them either.
        if entry.startswith('.'):
            continue

        path = os.path.join(directory, entry)
        if os.path.isdir(path):
            shutil.rmtree(path, True)
        else:
            os.unlink(path)


def get_html_path(path):
    warnings.warn(
        "get_html_path is never used in MkDocs and will be removed soon.", DeprecationWarning
    )
    path = os.path.splitext(path)[0]
    if os.path.basename(path) == 'index':
        return path + '.html'
    return "/".join((path, 'index.html'))


def get_url_path(path, use_directory_urls=True):
    warnings.warn(
        "get_url_path is never used in MkDocs and will be removed soon.", DeprecationWarning
    )
    path = get_html_path(path)
    url = '/' + path.replace(os.sep, '/')
    if use_directory_urls:
        return url[: -len('index.html')]
    return url


def is_markdown_file(path: str) -> bool:
    """
    Return True if the given file path is a Markdown file.

    https://superuser.com/questions/249436/file-extension-for-markdown-files
    """
    return path.endswith(markdown_extensions)


def is_html_file(path):
    warnings.warn(
        "is_html_file is never used in MkDocs and will be removed soon.", DeprecationWarning
    )
    return path.lower().endswith(('.html', '.htm'))


def is_template_file(path):
    warnings.warn(
        "is_template_file is never used in MkDocs and will be removed soon.", DeprecationWarning
    )
    return path.lower().endswith(('.html', '.htm', '.xml'))


_ERROR_TEMPLATE_RE = re.compile(r'^\d{3}\.html?$')


def is_error_template(path: str) -> bool:
    """
    Return True if the given file path is an HTTP error template.
    """
    return bool(_ERROR_TEMPLATE_RE.match(path))


@functools.lru_cache(maxsize=None)
def _norm_parts(path: str) -> List[str]:
    if not path.startswith('/'):
        path = '/' + path
    path = posixpath.normpath(path)[1:]
    return path.split('/') if path else []


def get_relative_url(url: str, other: str) -> str:
    """
    Return given url relative to other.

    Both are operated as slash-separated paths, similarly to the 'path' part of a URL.
    The last component of `other` is skipped if it contains a dot (considered a file).
    Actual URLs (with schemas etc.) aren't supported. The leading slash is ignored.
    Paths are normalized ('..' works as parent directory), but going higher than the
    root has no effect ('foo/../../bar' ends up just as 'bar').
    """
    # Remove filename from other url if it has one.
    dirname, _, basename = other.rpartition('/')
    if '.' in basename:
        other = dirname

    other_parts = _norm_parts(other)
    dest_parts = _norm_parts(url)
    common = 0
    for a, b in zip(other_parts, dest_parts):
        if a != b:
            break
        common += 1

    rel_parts = ['..'] * (len(other_parts) - common) + dest_parts[common:]
    relurl = '/'.join(rel_parts) or '.'
    return relurl + '/' if url.endswith('/') else relurl


def normalize_url(path: str, page: Optional[Page] = None, base: str = '') -> str:
    """Return a URL relative to the given page or using the base."""
    path, is_abs = _get_norm_url(path)
    if is_abs:
        return path
    if page is not None:
        return get_relative_url(path, page.url)
    return posixpath.join(base, path)


@functools.lru_cache(maxsize=None)
def _get_norm_url(path: str) -> Tuple[str, bool]:
    if not path:
        path = '.'
    elif os.sep != '/' and os.sep in path:
        log.warning(
            f"Path '{path}' uses OS-specific separator '{os.sep}', "
            f"change it to '/' so it is recognized on other systems."
        )
        path = path.replace(os.sep, '/')
    # Allow links to be fully qualified URLs
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or path.startswith(('/', '#')):
        return path, True
    return path, False


def create_media_urls(
    path_list: List[str], page: Optional[Page] = None, base: str = ''
) -> List[str]:
    """
    Return a list of URLs relative to the given page or using the base.
    """
    return [normalize_url(path, page, base) for path in path_list]


def path_to_url(path):
    """Soft-deprecated, do not use."""
    return path.replace('\\', '/')


def get_theme_dir(name: str) -> str:
    """Return the directory of an installed theme by name."""

    theme = get_themes()[name]
    return os.path.dirname(os.path.abspath(theme.load().__file__))


def get_themes() -> Dict[str, EntryPoint]:
    """Return a dict of all installed themes as {name: EntryPoint}."""

    themes: Dict[str, EntryPoint] = {}
    eps: Dict[EntryPoint, None] = dict.fromkeys(entry_points(group='mkdocs.themes'))
    builtins = {ep.name for ep in eps if ep.dist is not None and ep.dist.name == 'mkdocs'}

    for theme in eps:
        assert theme.dist is not None

        if theme.name in builtins and theme.dist.name != 'mkdocs':
            raise exceptions.ConfigurationError(
                f"The theme '{theme.name}' is a builtin theme but the package '{theme.dist.name}' "
                "attempts to provide a theme with the same name."
            )
        elif theme.name in themes:
            other_dist = themes[theme.name].dist
            assert other_dist is not None
            log.warning(
                f"A theme named '{theme.name}' is provided by the Python packages '{theme.dist.name}' "
                f"and '{other_dist.name}'. The one in '{theme.dist.name}' will be used."
            )

        themes[theme.name] = theme

    return themes


def get_theme_names():
    """Return a list of all installed themes by name."""

    return get_themes().keys()


def dirname_to_title(dirname: str) -> str:
    """Return a page tile obtained from a directory name."""
    title = dirname
    title = title.replace('-', ' ').replace('_', ' ')
    # Capitalize if the dirname was all lowercase, otherwise leave it as-is.
    if title.lower() == title:
        title = title.capitalize()

    return title


def get_markdown_title(markdown_src: str) -> Optional[str]:
    """
    Get the title of a Markdown document. The title in this case is considered
    to be a H1 that occurs before any other content in the document.
    The procedure is then to iterate through the lines, stopping at the first
    non-whitespace content. If it is a title, return that, otherwise return
    None.
    """
    lines = markdown_src.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    while lines:
        line = lines.pop(0).strip()
        if not line.strip():
            continue
        if not line.startswith('# '):
            return None
        return line.lstrip('# ')
    return None


def find_or_create_node(branch, key):
    """
    Given a list, look for dictionary with a key matching key and return it's
    value. If it doesn't exist, create it with the value of an empty list and
    return that.
    """
    for node in branch:
        if not isinstance(node, dict):
            continue

        if key in node:
            return node[key]

    new_branch = []
    node = {key: new_branch}
    branch.append(node)
    return new_branch


def nest_paths(paths):
    """
    Given a list of paths, convert them into a nested structure that will match
    the pages config.
    """
    nested = []

    for path in paths:
        parts = PurePath(path).parent.parts

        branch = nested
        for part in parts:
            part = dirname_to_title(part)
            branch = find_or_create_node(branch, part)

        branch.append(path)

    return nested


class CountHandler(logging.NullHandler):
    """Counts all logged messages >= level."""

    def __init__(self, **kwargs) -> None:
        self.counts: Dict[int, int] = defaultdict(int)
        super().__init__(**kwargs)

    def handle(self, record):
        rv = self.filter(record)
        if rv:
            # Use levelno for keys so they can be sorted later
            self.counts[record.levelno] += 1
        return rv

    def get_counts(self) -> List[Tuple[str, int]]:
        return [(logging.getLevelName(k), v) for k, v in sorted(self.counts.items(), reverse=True)]


# For backward compatibility as some plugins import it.
# It is no longer necessary as all messages on the
# `mkdocs` logger get counted automatically.
warning_filter = logging.Filter()
