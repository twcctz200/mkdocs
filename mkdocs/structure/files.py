from __future__ import annotations

import fnmatch
import logging
import os
import posixpath
import shutil
from pathlib import PurePath
from typing import TYPE_CHECKING, Dict, Iterable, Iterator, List, Optional, Sequence
from urllib.parse import quote as urlquote

import jinja2.environment

from mkdocs import utils
from mkdocs.config.base import Config

if TYPE_CHECKING:
    from mkdocs.structure.pages import Page

log = logging.getLogger(__name__)


class Files:
    """A collection of [File][mkdocs.structure.files.File] objects."""

    def __init__(self, files: List[File]) -> None:
        self._files = files
        self._src_uris: Optional[Dict[str, File]] = None

    def __iter__(self) -> Iterator[File]:
        """Iterate over the files within."""
        return iter(self._files)

    def __len__(self) -> int:
        """The number of files within."""
        return len(self._files)

    def __contains__(self, path: str) -> bool:
        """Whether the file with this `src_uri` is in the collection."""
        return PurePath(path).as_posix() in self.src_uris

    @property
    def src_paths(self) -> Dict[str, File]:
        """Soft-deprecated, prefer `src_uris`."""
        return {file.src_path: file for file in self._files}

    @property
    def src_uris(self) -> Dict[str, File]:
        """A mapping containing every file, with the keys being their
        [`src_uri`][mkdocs.structure.files.File.src_uri]."""
        if self._src_uris is None:
            self._src_uris = {file.src_uri: file for file in self._files}
        return self._src_uris

    def get_file_from_path(self, path: str) -> Optional[File]:
        """Return a File instance with File.src_uri equal to path."""
        return self.src_uris.get(PurePath(path).as_posix())

    def append(self, file: File) -> None:
        """Append file to Files collection."""
        self._src_uris = None
        self._files.append(file)

    def remove(self, file: File) -> None:
        """Remove file from Files collection."""
        self._src_uris = None
        self._files.remove(file)

    def copy_static_files(self, dirty: bool = False) -> None:
        """Copy static files from source to destination."""
        for file in self:
            if not file.is_documentation_page():
                file.copy_file(dirty)

    def documentation_pages(self) -> Sequence[File]:
        """Return iterable of all Markdown page file objects."""
        return [file for file in self if file.is_documentation_page()]

    def static_pages(self) -> Sequence[File]:
        """Return iterable of all static page file objects."""
        return [file for file in self if file.is_static_page()]

    def media_files(self) -> Sequence[File]:
        """Return iterable of all file objects which are not documentation or static pages."""
        return [file for file in self if file.is_media_file()]

    def javascript_files(self) -> Sequence[File]:
        """Return iterable of all javascript file objects."""
        return [file for file in self if file.is_javascript()]

    def css_files(self) -> Sequence[File]:
        """Return iterable of all CSS file objects."""
        return [file for file in self if file.is_css()]

    def add_files_from_theme(self, env: jinja2.Environment, config: Config) -> None:
        """Retrieve static files from Jinja environment and add to collection."""

        def filter(name):
            # '.*' filters dot files/dirs at root level whereas '*/.*' filters nested levels
            patterns = ['.*', '*/.*', '*.py', '*.pyc', '*.html', '*readme*', 'mkdocs_theme.yml']
            # Exclude translation files
            patterns.append("locales/*")
            patterns.extend(f'*{x}' for x in utils.markdown_extensions)
            patterns.extend(config['theme'].static_templates)
            for pattern in patterns:
                if fnmatch.fnmatch(name.lower(), pattern):
                    return False
            return True

        for path in env.list_templates(filter_func=filter):
            # Theme files do not override docs_dir files
            path = PurePath(path).as_posix()
            if path not in self.src_uris:
                for dir in config['theme'].dirs:
                    # Find the first theme dir which contains path
                    if os.path.isfile(os.path.join(dir, path)):
                        self.append(
                            File(path, dir, config['site_dir'], config['use_directory_urls'])
                        )
                        break


class File:
    """
    A MkDocs File object.

    Points to the source and destination locations of a file.

    The `path` argument must be a path that exists relative to `src_dir`.

    The `src_dir` and `dest_dir` must be absolute paths on the local file system.

    The `use_directory_urls` argument controls how destination paths are generated. If `False`, a Markdown file is
    mapped to an HTML file of the same name (the file extension is changed to `.html`). If True, a Markdown file is
    mapped to an HTML index file (`index.html`) nested in a directory using the "name" of the file in `path`. The
    `use_directory_urls` argument has no effect on non-Markdown files.

    File objects have the following properties, which are Unicode strings:
    """

    src_uri: str
    """The pure path (always '/'-separated) of the source file relative to the source directory."""

    abs_src_path: str
    """The absolute concrete path of the source file. Will use backslashes on Windows."""

    dest_uri: str
    """The pure path (always '/'-separated) of the destination file relative to the destination directory."""

    abs_dest_path: str
    """The absolute concrete path of the destination file. Will use backslashes on Windows."""

    url: str
    """The URI of the destination file relative to the destination directory as a string."""

    @property
    def src_path(self) -> str:
        """Same as `src_uri` (and synchronized with it) but will use backslashes on Windows. Discouraged."""
        return os.path.normpath(self.src_uri)

    @src_path.setter
    def src_path(self, value):
        self.src_uri = PurePath(value).as_posix()

    @property
    def dest_path(self) -> str:
        """Same as `dest_uri` (and synchronized with it) but will use backslashes on Windows. Discouraged."""
        return os.path.normpath(self.dest_uri)

    @dest_path.setter
    def dest_path(self, value):
        self.dest_uri = PurePath(value).as_posix()

    page: Optional[Page]

    def __init__(self, path: str, src_dir: str, dest_dir: str, use_directory_urls: bool) -> None:
        self.page = None
        self.src_path = path
        self.abs_src_path = os.path.normpath(os.path.join(src_dir, self.src_path))
        self.name = self._get_stem()
        self.dest_uri = self._get_dest_path(use_directory_urls)
        self.abs_dest_path = os.path.normpath(os.path.join(dest_dir, self.dest_path))
        self.url = self._get_url(use_directory_urls)

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, self.__class__)
            and self.src_uri == other.src_uri
            and self.abs_src_path == other.abs_src_path
            and self.url == other.url
        )

    def __repr__(self):
        return (
            f"File(src_uri='{self.src_uri}', dest_uri='{self.dest_uri}',"
            f" name='{self.name}', url='{self.url}')"
        )

    def _get_stem(self) -> str:
        """Return the name of the file without it's extension."""
        filename = posixpath.basename(self.src_uri)
        stem, ext = posixpath.splitext(filename)
        return 'index' if stem in ('index', 'README') else stem

    def _get_dest_path(self, use_directory_urls: bool) -> str:
        """Return destination path based on source path."""
        if self.is_documentation_page():
            parent, filename = posixpath.split(self.src_uri)
            if not use_directory_urls or self.name == 'index':
                # index.md or README.md => index.html
                # foo.md => foo.html
                return posixpath.join(parent, self.name + '.html')
            else:
                # foo.md => foo/index.html
                return posixpath.join(parent, self.name, 'index.html')
        return self.src_uri

    def _get_url(self, use_directory_urls: bool) -> str:
        """Return url based in destination path."""
        url = self.dest_uri
        dirname, filename = posixpath.split(url)
        if use_directory_urls and filename == 'index.html':
            if dirname == '':
                url = '.'
            else:
                url = dirname + '/'
        return urlquote(url)

    def url_relative_to(self, other: File) -> str:
        """Return url for file relative to other file."""
        return utils.get_relative_url(self.url, other.url if isinstance(other, File) else other)

    def copy_file(self, dirty: bool = False) -> None:
        """Copy source file to destination, ensuring parent directories exist."""
        if dirty and not self.is_modified():
            log.debug(f"Skip copying unmodified file: '{self.src_uri}'")
        else:
            log.debug(f"Copying media file: '{self.src_uri}'")
            try:
                utils.copy_file(self.abs_src_path, self.abs_dest_path)
            except shutil.SameFileError:
                pass  # Let plugins write directly into site_dir.

    def is_modified(self) -> bool:
        if os.path.isfile(self.abs_dest_path):
            return os.path.getmtime(self.abs_dest_path) < os.path.getmtime(self.abs_src_path)
        return True

    def is_documentation_page(self) -> bool:
        """Return True if file is a Markdown page."""
        return utils.is_markdown_file(self.src_uri)

    def is_static_page(self) -> bool:
        """Return True if file is a static page (HTML, XML, JSON)."""
        return self.src_uri.endswith(('.html', '.htm', '.xml', '.json'))

    def is_media_file(self) -> bool:
        """Return True if file is not a documentation or static page."""
        return not (self.is_documentation_page() or self.is_static_page())

    def is_javascript(self) -> bool:
        """Return True if file is a JavaScript file."""
        return self.src_uri.endswith(('.js', '.javascript'))

    def is_css(self) -> bool:
        """Return True if file is a CSS file."""
        return self.src_uri.endswith('.css')


def get_files(config: Config) -> Files:
    """Walk the `docs_dir` and return a Files collection."""
    files = []
    exclude = ['.*', '/templates']

    for source_dir, dirnames, filenames in os.walk(config['docs_dir'], followlinks=True):
        relative_dir = os.path.relpath(source_dir, config['docs_dir'])

        for dirname in list(dirnames):
            path = os.path.normpath(os.path.join(relative_dir, dirname))
            # Skip any excluded directories
            if _filter_paths(basename=dirname, path=path, is_dir=True, exclude=exclude):
                dirnames.remove(dirname)
        dirnames.sort()

        for filename in _sort_files(filenames):
            path = os.path.normpath(os.path.join(relative_dir, filename))
            # Skip any excluded files
            if _filter_paths(basename=filename, path=path, is_dir=False, exclude=exclude):
                continue
            # Skip README.md if an index file also exists in dir
            if filename == 'README.md' and 'index.md' in filenames:
                log.warning(
                    f"Both index.md and README.md found. Skipping README.md from {source_dir}"
                )
                continue
            files.append(
                File(path, config['docs_dir'], config['site_dir'], config['use_directory_urls'])
            )

    return Files(files)


def _sort_files(filenames: Iterable[str]) -> List[str]:
    """Always sort `index` or `README` as first filename in list."""

    def key(f):
        if os.path.splitext(f)[0] in ['index', 'README']:
            return (0,)
        return (1, f)

    return sorted(filenames, key=key)


def _filter_paths(basename: str, path: str, is_dir: bool, exclude: Iterable[str]) -> bool:
    """.gitignore style file filtering."""
    for item in exclude:
        # Items ending in '/' apply only to directories.
        if item.endswith('/') and not is_dir:
            continue
        # Items starting with '/' apply to the whole path.
        # In any other cases just the basename is used.
        match = path if item.startswith('/') else basename
        if fnmatch.fnmatch(match, item.strip('/')):
            return True
    return False
