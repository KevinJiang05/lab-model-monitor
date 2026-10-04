"""Local HTML exports and cached screenshots; never issues model requests."""
from __future__ import annotations

import base64
import html
import json
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import UUID

from .animation import projection

MAX_THUMBNAIL_BYTES = 180_000


def thumbnail_data(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size > MAX_THUMBNAIL_BYTES:
        return None
    data = path.read_bytes()
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        return None
    return 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')


def capture_thumbnail(source: str, destination: Path) -> None:
    browser = next((p for p in (
        Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
    ) if p.is_file()), None)
    if browser is None:
        raise RuntimeError('Thumbnail browser unavailable')
    policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    # A fresh browser profile and opaque iframe match the hosted preview isolation.
    # Put CSP first so model markup cannot load external resources before it applies.
    isolated = '<meta http-equiv="Content-Security-Policy" content="' + policy + '">' + source
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.capture-') as temp:
        root = Path(temp)
        wrapper = root / 'preview.html'
        wrapper.write_text('<!doctype html><style>html,body{margin:0;overflow:hidden;background:white}iframe{border:0;width:1366px;height:900px;transform:scale(.351391);transform-origin:top left}</style><iframe sandbox="allow-scripts" srcdoc="' + html.escape(isolated, quote=True) + '"></iframe>', encoding='utf-8')
        output = root / 'thumbnail.png'
        command = [str(browser), '--headless=new', '--disable-gpu', '--no-first-run',
                   '--no-default-browser-check', '--disable-background-networking', '--hide-scrollbars',
                   '--run-all-compositor-stages-before-draw', '--force-device-scale-factor=1', '--window-size=480,317', '--virtual-time-budget=3000',
                   '--user-data-dir=' + str(root / 'profile'), '--screenshot=' + str(output), wrapper.as_uri()]
        for attempt in range(2):
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                process.wait(timeout=5)
                raise RuntimeError('Thumbnail timed out') from None
            if process.returncode or thumbnail_data(output) is None or output.stat().st_size < 2500:
                if attempt == 0:
                    continue
                raise RuntimeError('Thumbnail capture failed')
            break
        output.replace(destination)


def export_run(run: dict, root: Path, *, renderer=capture_thumbnail) -> dict:
    payload = projection(run)
    directory = root / str(UUID(payload['run_id']))
    directory.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for index, sample in enumerate(payload['samples'], 1):
        if not sample['html']:
            continue
        item = {'model': sample['requested_model'], 'html': 'failed', 'thumbnail': 'ready'}
        try:
            (directory / f'model-{index}.html').write_text(sample['html'], encoding='utf-8', newline='')
            item['html'] = 'saved'
            target = directory / f"{sample['sha256']}.png"
            if thumbnail_data(target) is None:
                renderer(sample['html'], target)
            if thumbnail_data(target) is None:
                raise RuntimeError('Invalid thumbnail')
        except Exception as exc:
            item.update(thumbnail='failed', error_type=type(exc).__name__)
        outcomes.append(item)
    (directory / 'display.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    result = {'success': all(s['thumbnail'] == 'ready' for s in outcomes), 'samples': outcomes}
    (directory / 'artifacts.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def prepare_run(store, run_id: str) -> dict:
    try:
        result = export_run(store.get(run_id), store.path.parent / 'artifacts')
    except Exception as exc:
        result = {'success': False, 'status': 'export_failed', 'error_type': type(exc).__name__}
    store.delivery(run_id, 'artifacts', result)
    return result
