from __future__ import annotations

import logging
from typing import Iterator, List, Optional, Type, TypeVar, Union
from urllib.parse import urlsplit

from mkdocs.config.base import Config
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page
from mkdocs.utils import nest_paths

log = logging.getLogger(__name__)


class Navigation:
    def __init__(self, items: List[Union[Page, Section, Link]], pages: List[Page]) -> None:
        self.items = items  # Nested List with full navigation of Sections, Pages, and Links.
        self.pages = pages  # Flat List of subset of Pages in nav, in order.

        self.homepage = None
        for page in pages:
            if page.is_homepage:
                self.homepage = page
                break

    homepage: Optional[Page]
    """The [page][mkdocs.structure.pages.Page] object for the homepage of the site."""

    pages: List[Page]
    """A flat list of all [page][mkdocs.structure.pages.Page] objects contained in the navigation."""

    def __repr__(self):
        return '\n'.join(item._indent_print() for item in self)

    def __iter__(self) -> Iterator[Union[Page, Section, Link]]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


class Section:
    def __init__(self, title: str, children: List[Union[Page, Section, Link]]) -> None:
        self.title = title
        self.children = children

        self.parent = None
        self.active = False

    def __repr__(self):
        return f"Section(title='{self.title}')"

    title: str
    """The title of the section."""

    parent: Optional[Section]
    """The immediate parent of the section or `None` if the section is at the top level."""

    children: List[Union[Page, Section, Link]]
    """An iterable of all child navigation objects. Children may include nested sections, pages and links."""

    @property
    def active(self) -> bool:
        """
        When `True`, indicates that a child page of this section is the current page and
        can be used to highlight the section as the currently viewed section. Defaults
        to `False`.
        """
        return self.__active

    @active.setter
    def active(self, value: bool):
        """Set active status of section and ancestors."""
        self.__active = bool(value)
        if self.parent is not None:
            self.parent.active = bool(value)

    is_section: bool = True
    """Indicates that the navigation object is a "section" object. Always `True` for section objects."""

    is_page: bool = False
    """Indicates that the navigation object is a "page" object. Always `False` for section objects."""

    is_link: bool = False
    """Indicates that the navigation object is a "link" object. Always `False` for section objects."""

    @property
    def ancestors(self):
        if self.parent is None:
            return []
        return [self.parent] + self.parent.ancestors

    def _indent_print(self, depth=0):
        ret = ['{}{}'.format('    ' * depth, repr(self))]
        for item in self.children:
            ret.append(item._indent_print(depth + 1))
        return '\n'.join(ret)


class Link:
    def __init__(self, title: str, url: str):
        self.title = title
        self.url = url
        self.parent = None

    def __repr__(self):
        title = f"'{self.title}'" if (self.title is not None) else '[blank]'
        return f"Link(title={title}, url='{self.url}')"

    title: str
    """The title of the link. This would generally be used as the label of the link."""

    url: str
    """The URL that the link points to. The URL should always be an absolute URLs and
    should not need to have `base_url` prepended."""

    parent: Optional[Section]
    """The immediate parent of the link. `None` if the link is at the top level."""

    children: None = None
    """Links do not contain children and the attribute is always `None`."""

    active: bool = False
    """External links cannot be "active" and the attribute is always `False`."""

    is_section: bool = False
    """Indicates that the navigation object is a "section" object. Always `False` for link objects."""

    is_page: bool = False
    """Indicates that the navigation object is a "page" object. Always `False` for link objects."""

    is_link: bool = True
    """Indicates that the navigation object is a "link" object. Always `True` for link objects."""

    @property
    def ancestors(self):
        if self.parent is None:
            return []
        return [self.parent] + self.parent.ancestors

    def _indent_print(self, depth=0):
        return '{}{}'.format('    ' * depth, repr(self))


def get_navigation(files: Files, config: Config) -> Navigation:
    """Build site navigation from config and files."""
    nav_config = config['nav'] or nest_paths(f.src_uri for f in files.documentation_pages())
    items = _data_to_navigation(nav_config, files, config)
    if not isinstance(items, list):
        items = [items]

    # Get only the pages from the navigation, ignoring any sections and links.
    pages = _get_by_type(items, Page)

    # Include next, previous and parent links.
    _add_previous_and_next_links(pages)
    _add_parent_links(items)

    missing_from_config = [file for file in files.documentation_pages() if file.page is None]
    if missing_from_config:
        log.info(
            'The following pages exist in the docs directory, but are not '
            'included in the "nav" configuration:\n  - {}'.format(
                '\n  - '.join(file.src_path for file in missing_from_config)
            )
        )
        # Any documentation files not found in the nav should still have an associated page, so we
        # create them here. The Page object will automatically be assigned to `file.page` during
        # its creation (and this is the only way in which these page objects are accessible).
        for file in missing_from_config:
            Page(None, file, config)

    links = _get_by_type(items, Link)
    for link in links:
        scheme, netloc, path, query, fragment = urlsplit(link.url)
        if scheme or netloc:
            log.debug(f"An external link to '{link.url}' is included in the 'nav' configuration.")
        elif link.url.startswith('/'):
            log.debug(
                f"An absolute path to '{link.url}' is included in the 'nav' "
                "configuration, which presumably points to an external resource."
            )
        else:
            msg = (
                f"A relative path to '{link.url}' is included in the 'nav' "
                "configuration, which is not found in the documentation files"
            )
            log.warning(msg)
    return Navigation(items, pages)


def _data_to_navigation(data, files: Files, config: Config):
    if isinstance(data, dict):
        return [
            _data_to_navigation((key, value), files, config)
            if isinstance(value, str)
            else Section(title=key, children=_data_to_navigation(value, files, config))
            for key, value in data.items()
        ]
    elif isinstance(data, list):
        return [
            _data_to_navigation(item, files, config)[0]
            if isinstance(item, dict) and len(item) == 1
            else _data_to_navigation(item, files, config)
            for item in data
        ]
    title, path = data if isinstance(data, tuple) else (None, data)
    file = files.get_file_from_path(path)
    if file:
        return Page(title, file, config)
    return Link(title, path)


T = TypeVar('T')


def _get_by_type(nav, T: Type[T]) -> List[T]:
    ret = []
    for item in nav:
        if isinstance(item, T):
            ret.append(item)
        if item.children:
            ret.extend(_get_by_type(item.children, T))
    return ret


def _add_parent_links(nav) -> None:
    for item in nav:
        if item.is_section:
            for child in item.children:
                child.parent = item
            _add_parent_links(item.children)


def _add_previous_and_next_links(pages: List[Page]) -> None:
    bookended = [None, *pages, None]
    zipped = zip(bookended[:-2], pages, bookended[2:])
    for page0, page1, page2 in zipped:
        page1.previous_page, page1.next_page = page0, page2
