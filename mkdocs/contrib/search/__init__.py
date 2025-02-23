from __future__ import annotations

import logging
import os
from typing import Any, Dict

from mkdocs import utils
from mkdocs.config import base, config_options
from mkdocs.config.base import Config
from mkdocs.contrib.search.search_index import SearchIndex
from mkdocs.plugins import BasePlugin

log = logging.getLogger(__name__)
base_path = os.path.dirname(os.path.abspath(__file__))


class LangOption(config_options.OptionallyRequired):
    """Validate Language(s) provided in config are known languages."""

    def get_lunr_supported_lang(self, lang):
        for lang_part in lang.split("_"):
            lang_part = lang_part.lower()
            if os.path.isfile(os.path.join(base_path, 'lunr-language', f'lunr.{lang_part}.js')):
                return lang_part

    def run_validation(self, value):
        if isinstance(value, str):
            value = [value]
        elif not isinstance(value, (list, tuple)):
            raise config_options.ValidationError('Expected a list of language codes.')
        for lang in list(value):
            if lang != 'en':
                lang_detected = self.get_lunr_supported_lang(lang)
                if not lang_detected:
                    log.info(f"Option search.lang '{lang}' is not supported, falling back to 'en'")
                    value.remove(lang)
                    if 'en' not in value:
                        value.append('en')
                elif lang_detected != lang:
                    value.remove(lang)
                    value.append(lang_detected)
                    log.info(f"Option search.lang '{lang}' switched to '{lang_detected}'")
        return value


class _PluginConfig:
    lang = LangOption()
    separator = config_options.Type(str, default=r'[\s\-]+')
    min_search_length = config_options.Type(int, default=3)
    prebuild_index = config_options.Choice((False, True, 'node', 'python'), default=False)
    indexing = config_options.Choice(('full', 'sections', 'titles'), default='full')


class SearchPlugin(BasePlugin):
    """Add a search feature to MkDocs."""

    config_scheme = base.get_schema(_PluginConfig)

    def on_config(self, config: Config, **kwargs) -> Config:
        "Add plugin templates and scripts to config."
        if 'include_search_page' in config['theme'] and config['theme']['include_search_page']:
            config['theme'].static_templates.add('search.html')
        if not ('search_index_only' in config['theme'] and config['theme']['search_index_only']):
            path = os.path.join(base_path, 'templates')
            config['theme'].dirs.append(path)
            if 'search/main.js' not in config['extra_javascript']:
                config['extra_javascript'].append('search/main.js')
        if self.config['lang'] is None:
            # lang setting undefined. Set default based on theme locale
            validate = _PluginConfig.lang.run_validation
            self.config['lang'] = validate(config['theme']['locale'].language)
        # The `python` method of `prebuild_index` is pending deprecation as of version 1.2.
        # TODO: Raise a deprecation warning in a future release (1.3?).
        if self.config['prebuild_index'] == 'python':
            log.info(
                "The 'python' method of the search plugin's 'prebuild_index' config option "
                "is pending deprecation and will not be supported in a future release."
            )
        return config

    def on_pre_build(self, config: Config, *args, **kwargs) -> None:
        "Create search index instance for later use."
        self.search_index = SearchIndex(**self.config)

    def on_page_context(self, context: Dict[str, Any], *args, **kwargs) -> None:
        "Add page to search index."
        self.search_index.add_entry_from_context(context['page'])

    def on_post_build(self, config: Config, **kwargs) -> None:
        "Build search index."
        output_base_path = os.path.join(config['site_dir'], 'search')
        search_index = self.search_index.generate_search_index()
        json_output_path = os.path.join(output_base_path, 'search_index.json')
        utils.write_file(search_index.encode('utf-8'), json_output_path)

        if not ('search_index_only' in config['theme'] and config['theme']['search_index_only']):
            # Include language support files in output. Copy them directly
            # so that only the needed files are included.
            files = []
            if len(self.config['lang']) > 1 or 'en' not in self.config['lang']:
                files.append('lunr.stemmer.support.js')
            if len(self.config['lang']) > 1:
                files.append('lunr.multi.js')
            if 'ja' in self.config['lang'] or 'jp' in self.config['lang']:
                files.append('tinyseg.js')
            for lang in self.config['lang']:
                if lang != 'en':
                    files.append(f'lunr.{lang}.js')

            for filename in files:
                from_path = os.path.join(base_path, 'lunr-language', filename)
                to_path = os.path.join(output_base_path, filename)
                utils.copy_file(from_path, to_path)
