#!/usr/bin/env python

from __future__ import annotations

import logging
import os
import shutil
import sys
import textwrap
import traceback
import warnings

import click

from mkdocs import __version__, config, utils

if sys.platform.startswith("win"):
    try:
        import colorama
    except ImportError:
        pass
    else:
        colorama.init()

log = logging.getLogger(__name__)


def _showwarning(message, category, filename, lineno, file=None, line=None):
    try:
        # Last stack frames:
        # * ...
        # * Location of call to deprecated function   <-- include this
        # * Location of call to warn()                <-- include this
        # * (stdlib) Location of call to showwarning function
        # * (this function) Location of call to extract_stack()
        stack = traceback.extract_stack()[-4:-2]
        tb = ''.join(traceback.format_list(stack))
    except Exception:
        tb = f'  File "{filename}", line {lineno}'

    log.info(f'{category.__name__}: {message}\n{tb}')


def _enable_warnings():
    warnings.simplefilter('module', DeprecationWarning)
    warnings.showwarning = _showwarning


class ColorFormatter(logging.Formatter):
    colors = {
        'CRITICAL': 'red',
        'ERROR': 'red',
        'WARNING': 'yellow',
        'DEBUG': 'blue',
    }

    text_wrapper = textwrap.TextWrapper(
        width=shutil.get_terminal_size(fallback=(0, 0)).columns,
        replace_whitespace=False,
        break_long_words=False,
        break_on_hyphens=False,
        initial_indent=' ' * 12,
        subsequent_indent=' ' * 12,
    )

    def format(self, record):
        message = super().format(record)
        prefix = f'{record.levelname:<8} -  '
        if record.levelname in self.colors:
            prefix = click.style(prefix, fg=self.colors[record.levelname])
        if self.text_wrapper.width:
            # Only wrap text if a terminal width was detected
            msg = '\n'.join(self.text_wrapper.fill(line) for line in message.splitlines())
            # Prepend prefix after wrapping so that color codes don't affect length
            return prefix + msg[12:]
        return prefix + message


class State:
    """Maintain logging level."""

    def __init__(self, log_name='mkdocs', level=logging.INFO):
        self.logger = logging.getLogger(log_name)
        # Don't restrict level on logger; use handler
        self.logger.setLevel(1)
        self.logger.propagate = False

        self.stream = logging.StreamHandler()
        self.stream.setFormatter(ColorFormatter())
        self.stream.setLevel(level)
        self.stream.name = 'MkDocsStreamHandler'
        self.logger.addHandler(self.stream)

    def __del__(self):
        self.logger.removeHandler(self.stream)


pass_state = click.make_pass_decorator(State, ensure=True)

clean_help = "Remove old files from the site_dir before building (the default)."
config_help = "Provide a specific MkDocs config"
dev_addr_help = "IP address and port to serve documentation locally (default: localhost:8000)"
strict_help = "Enable strict mode. This will cause MkDocs to abort the build on any warnings."
theme_help = "The theme to use when building your documentation."
theme_choices = utils.get_theme_names()
site_dir_help = "The directory to output the result of the documentation build."
use_directory_urls_help = "Use directory URLs when building pages (the default)."
reload_help = "Enable the live reloading in the development server (this is the default)"
no_reload_help = "Disable the live reloading in the development server."
dirty_reload_help = (
    "Enable the live reloading in the development server, but only re-build files that have changed"
)
commit_message_help = (
    "A commit message to use when committing to the "
    "GitHub Pages remote branch. Commit {sha} and MkDocs {version} are available as expansions"
)
remote_branch_help = (
    "The remote branch to commit to for GitHub Pages. This "
    "overrides the value specified in config"
)
remote_name_help = (
    "The remote name to commit to for GitHub Pages. This overrides the value specified in config"
)
force_help = "Force the push to the repository."
no_history_help = "Replace the whole Git history with one new commit."
ignore_version_help = (
    "Ignore check that build is not being deployed with an older version of MkDocs."
)
watch_theme_help = (
    "Include the theme in list of files to watch for live reloading. "
    "Ignored when live reload is not used."
)
shell_help = "Use the shell when invoking Git."
watch_help = "A directory or file to watch for live reloading. Can be supplied multiple times."


def add_options(*opts):
    def inner(f):
        for i in reversed(opts):
            f = i(f)
        return f

    return inner


def verbose_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.stream.setLevel(logging.DEBUG)

    return click.option(
        '-v',
        '--verbose',
        is_flag=True,
        expose_value=False,
        help='Enable verbose output',
        callback=callback,
    )(f)


def quiet_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.stream.setLevel(logging.ERROR)

    return click.option(
        '-q',
        '--quiet',
        is_flag=True,
        expose_value=False,
        help='Silence warnings',
        callback=callback,
    )(f)


common_options = add_options(quiet_option, verbose_option)
common_config_options = add_options(
    click.option('-f', '--config-file', type=click.File('rb'), help=config_help),
    # Don't override config value if user did not specify --strict flag
    # Conveniently, load_config drops None values
    click.option('-s', '--strict', is_flag=True, default=None, help=strict_help),
    click.option('-t', '--theme', type=click.Choice(theme_choices), help=theme_help),
    # As with --strict, set the default to None so that this doesn't incorrectly
    # override the config file
    click.option(
        '--use-directory-urls/--no-directory-urls',
        is_flag=True,
        default=None,
        help=use_directory_urls_help,
    ),
)

PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"

PKG_DIR = os.path.dirname(os.path.abspath(__file__))


@click.group(context_settings={'help_option_names': ['-h', '--help']})
@click.version_option(
    __version__,
    '-V',
    '--version',
    message=f'%(prog)s, version %(version)s from { PKG_DIR } (Python { PYTHON_VERSION })',
)
@common_options
def cli():
    """
    MkDocs - Project documentation with Markdown.
    """


@cli.command(name="serve")
@click.option('-a', '--dev-addr', help=dev_addr_help, metavar='<IP:PORT>')
@click.option('--livereload', 'livereload', flag_value='livereload', help=reload_help, default=True)
@click.option('--no-livereload', 'livereload', flag_value='no-livereload', help=no_reload_help)
@click.option('--dirtyreload', 'livereload', flag_value='dirty', help=dirty_reload_help)
@click.option('--watch-theme', help=watch_theme_help, is_flag=True)
@click.option(
    '-w', '--watch', help=watch_help, type=click.Path(exists=True), multiple=True, default=[]
)
@common_config_options
@common_options
def serve_command(dev_addr, livereload, watch, **kwargs):
    """Run the builtin development server"""
    from mkdocs.commands import serve

    _enable_warnings()
    serve.serve(dev_addr=dev_addr, livereload=livereload, watch=watch, **kwargs)


@cli.command(name="build")
@click.option('-c', '--clean/--dirty', is_flag=True, default=True, help=clean_help)
@common_config_options
@click.option('-d', '--site-dir', type=click.Path(), help=site_dir_help)
@common_options
def build_command(clean, **kwargs):
    """Build the MkDocs documentation"""
    from mkdocs.commands import build

    _enable_warnings()
    build.build(config.load_config(**kwargs), dirty=not clean)


@cli.command(name="gh-deploy")
@click.option('-c', '--clean/--dirty', is_flag=True, default=True, help=clean_help)
@click.option('-m', '--message', help=commit_message_help)
@click.option('-b', '--remote-branch', help=remote_branch_help)
@click.option('-r', '--remote-name', help=remote_name_help)
@click.option('--force', is_flag=True, help=force_help)
@click.option('--no-history', is_flag=True, help=no_history_help)
@click.option('--ignore-version', is_flag=True, help=ignore_version_help)
@click.option('--shell', is_flag=True, help=shell_help)
@common_config_options
@click.option('-d', '--site-dir', type=click.Path(), help=site_dir_help)
@common_options
def gh_deploy_command(
    clean, message, remote_branch, remote_name, force, no_history, ignore_version, shell, **kwargs
):
    """Deploy your documentation to GitHub Pages"""
    from mkdocs.commands import build, gh_deploy

    _enable_warnings()
    cfg = config.load_config(remote_branch=remote_branch, remote_name=remote_name, **kwargs)
    build.build(cfg, dirty=not clean)
    gh_deploy.gh_deploy(
        cfg,
        message=message,
        force=force,
        no_history=no_history,
        ignore_version=ignore_version,
        shell=shell,
    )


@cli.command(name="new")
@click.argument("project_directory")
@common_options
def new_command(project_directory):
    """Create a new MkDocs project"""
    from mkdocs.commands import new

    new.new(project_directory)


if __name__ == '__main__':  # pragma: no cover
    cli()
