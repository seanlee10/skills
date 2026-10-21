# /// script
# requires-python = "==3.11.*"
# dependencies = [
#     "pillow==12.3.0",
# ]
# ///
"""Pick photos and videos from Google Photos with the Picker API and curate them locally.

Usage: uv run gphoto.py {check,auth,start,fetch,curate,select} [options]

Exit 0: one JSON object on stdout. Exit 2: {"status":"failed","error":CODE,"message":str} on stderr.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never leave __pycache__ inside the skill folder

import argparse
import json
import shutil
from typing import Callable

from gphoto import auth, config, curate, errors, fetch, library
from gphoto.errors import Failure

SUBCOMMANDS = ('check', 'auth', 'start', 'fetch', 'curate', 'select')


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse's message may echo arguments; keep it out of stderr
        raise Failure('USAGE_ERROR')


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog='gphoto.py', description='Pick and curate Google Photos via the Picker API.')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help='report whether this machine is ready')
    sub.add_parser('auth', help='sign in to Google Photos in the browser')
    start = sub.add_parser('start', help='create a Google Photos picking session')
    start.add_argument('--subject', required=True, help='folder name for who or what is pictured')
    start.add_argument('--year', required=True, type=int)
    start.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD')
    start.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD')
    start.add_argument('--type', choices=('photo', 'video', 'all'), default='all')
    start.add_argument('--camera', metavar='TEXT')
    start.add_argument('--orientation', choices=('portrait', 'landscape'))
    start.add_argument('--min-side', type=int, metavar='PX')
    start.add_argument('--tz', metavar='ZONE', help='IANA time zone for dates (default: this machine)')
    start.add_argument('--out-root', metavar='DIR', help=f'library root (default {library.DEFAULT_OUT_ROOT})')
    start.add_argument('--search', metavar='TEXT', help='text to search in the picker (default: subject)')
    start.add_argument('--no-browser', action='store_true', help='do not open the picker link in the browser')
    fetch_p = sub.add_parser('fetch', help='wait for Done, then download the picked items')
    fetch_p.add_argument('--session', metavar='ID', help='pending session (default: the only one)')
    fetch_p.add_argument('--wait', type=float, default=540, metavar='SECONDS')
    curate_p = sub.add_parser('curate', help='pre-filter the year folder and draw contact sheets')
    curate_p.add_argument('--subject', required=True, help='folder name for who or what is pictured')
    curate_p.add_argument('--year', required=True, type=int)
    curate_p.add_argument('--out-root', metavar='DIR', help=f'library root (default {library.DEFAULT_OUT_ROOT})')
    curate_p.add_argument('--target', type=int, default=curate.DEFAULT_TARGET, metavar='N',
                          help='photos wanted in the end (candidates: N x %d)' % curate.CANDIDATE_FACTOR)
    curate_p.add_argument('--video-target', type=int, default=curate.DEFAULT_VIDEO_TARGET, metavar='N',
                          help='videos wanted in the end')
    select_p = sub.add_parser('select', help="apply the agent's ranked picks to selected/")
    select_p.add_argument('--subject', required=True, help='folder name for who or what is pictured')
    select_p.add_argument('--year', required=True, type=int)
    select_p.add_argument('--out-root', metavar='DIR', help=f'library root (default {library.DEFAULT_OUT_ROOT})')
    select_p.add_argument('--picks', metavar='FILE', help='picks file (default: the year\'s curation/picks.json)')
    return p


def check(args: argparse.Namespace) -> dict:
    """Readiness report: never reads or prints the client secret or tokens."""
    cfg = config.config_dir()
    return {
        'status': 'ok',
        'local': True,  # ensure_local() already passed
        'client_secret': 'present' if config.client_secret_path().is_file() else 'missing',
        'token': auth.token_state(),  # presence only; validity needs the network
        'ffmpeg': 'present' if shutil.which('ffmpeg') and shutil.which('ffprobe') else 'missing',
        'config_dir': str(cfg),
    }


def auth_command(args: argparse.Namespace) -> dict:
    """Browser sign-in; the token is saved to the config folder and never printed."""
    auth.sign_in(config.load_client())
    return {'status': 'ok', 'signed_in': True}


def _token() -> str:
    return auth.access_token(config.load_client())


def start_command(args: argparse.Namespace) -> dict:
    """Create a picking session and open its link in the browser; prints the link, never a token."""
    return fetch.run_start(args.subject, args.year, _token, date_from=args.date_from,
                           date_to=args.date_to, type=args.type, camera=args.camera,
                           orientation=args.orientation, min_side=args.min_side, tz=args.tz,
                           out_root=args.out_root, search=args.search, browser=not args.no_browser)


def fetch_command(args: argparse.Namespace) -> dict:
    """Wait for the user's Done, then download the picked items into the library."""
    if not args.wait >= 0 or args.wait == float('inf'):
        raise Failure('USAGE_ERROR')
    return fetch.run_fetch(args.session, args.wait, _token)


def curate_command(args: argparse.Namespace) -> dict:
    """Local pre-filter and contact sheets; writes only inside the year's curation/ folder."""
    return curate.run_curate(args.subject, args.year, out_root=args.out_root, target=args.target,
                             video_target=args.video_target)


def select_command(args: argparse.Namespace) -> dict:
    """Apply the picks: rebuilds selected/ and selection.json; media/ is never changed."""
    return curate.run_select(args.subject, args.year, out_root=args.out_root, picks_file=args.picks)


COMMANDS: dict[str, Callable[[argparse.Namespace], dict]] = {
    'check': check,
    'auth': auth_command,
    'start': start_command,
    'fetch': fetch_command,
    'curate': curate_command,
    'select': select_command,
}


def _fail(code: str) -> int:
    sys.stderr.write(json.dumps({'status': 'failed', 'error': code, 'message': errors.message_for(code)},
                                ensure_ascii=False) + '\n')
    return 2


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)  # --help exits here, before the local-only guard
        config.ensure_local()
        command = COMMANDS.get(args.command)
        if command is None:
            raise Failure('USAGE_ERROR')  # subcommand not implemented yet
        summary = command(args)
    except Failure as e:
        return _fail(e.code)  # codes are fixed identifiers; unknown ones get GENERIC_MESSAGE
    except Exception as e:  # never print tracebacks, paths or secrets
        return _fail(type(e).__name__)
    except KeyboardInterrupt:  # Ctrl-C: a JSON failure, not a traceback
        return _fail('INTERRUPTED')
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
