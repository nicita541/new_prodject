"""Owned lifecycle of the existing official-CLI script; never handles credentials or answers."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from .config import ROOT
from .json_store import atomic_json, now, read_json


def configure_default(directory, provider):
    if provider != 'antigravity_manual':
        return
    directory=Path(directory).resolve()
    root=(directory/'antigravity').resolve()
    root.relative_to(directory)
    path=root/'automation.json'
    if not path.exists():
        atomic_json(path,{'enabled':True,'managed':True})


def cli_executable():
    located = shutil.which('agy')
    candidate = Path(located) if located else Path(os.environ.get('LOCALAPPDATA',''))/'agy/bin/agy.exe'
    if not candidate.is_file() or candidate.suffix.lower() != '.exe':
        raise RuntimeError('Antigravity CLI не найден. Установленный официальный agy.exe должен быть доступен в PATH.')
    return candidate.resolve()


class ManagedRunner:
    def __init__(self,directory,cancelled):
        self.directory = Path(directory).resolve()
        self.directory.relative_to(ROOT.resolve())
        self.root = (self.directory/'antigravity').resolve()
        self.root.relative_to(self.directory)
        self.cancelled = cancelled
        self.process = None
        self.log = None
        self.stopping = threading.Event()
        self.monitor = None
        self.stop_file = self.root/('.managed-stop-'+uuid.uuid4().hex)

    def _state(self):
        try:
            return read_json(self.root/'runner.json',{})
        except (OSError,ValueError):
            return {}

    def _failure(self,code):
        state = self._state()
        atomic_json(self.root/'runner.json',{**state,'status':'error','owner':'worker',
            'exit_code':code,'message':'Автоматический процесс Antigravity завершился; проверьте runner.log',
            'updated_at':now()})

    def start(self):
        automation = read_json(self.root/'automation.json',{})
        job = read_json(self.directory/'job.json',{})
        if (job.get('analysis_provider') != 'antigravity_manual' or automation.get('enabled') is not True
                or automation.get('managed') is not True):
            return self
        if self.cancelled():
            raise InterruptedError('Обработка отменена')
        # A separately user-started runner owns its lock and cancellation.
        # Reuse it without trying to terminate or impersonate that process.
        lock = self.root/'runner.lock'
        try:
            with lock.open('a+b'):
                pass
        except PermissionError:
            if self._state().get('status') in ('waiting','processing'):
                return self
            raise RuntimeError('Папка обмена Antigravity заблокирована другим процессом') from None
        executable = cli_executable()
        from .antigravity_quota import seed_cooldown
        seed_cooldown(self.directory)
        script = ROOT/'scripts/run_antigravity_job.ps1'
        if not script.is_file():
            raise RuntimeError('Сценарий автоматического обмена Antigravity отсутствует')
        command = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),
                   '-JobDirectory',str(self.directory),'-AgyExe',str(executable),
                   '-ManagedStopFile',str(self.stop_file)]
        env = dict(os.environ)
        env.update(TEMP=str(ROOT/'temp'),TMP=str(ROOT/'temp'),TMPDIR=str(ROOT/'temp'),
                   XDG_CACHE_HOME=str(ROOT/'cache/agy'))
        # Archive stale hints so readiness cannot mistake an old runner for
        # this process. Preserve its diagnostics without changing packet caches.
        previous=self.root/'runner.json'
        if previous.exists():
            history=self.root/'runner-history'
            history.mkdir(exist_ok=True)
            previous.rename(history/(uuid.uuid4().hex+'.json'))
        self.log = (self.root/'runner.log').open('ab')
        try:
            self.process = subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
                stdout=self.log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            deadline = time.monotonic()+15
            while time.monotonic() < deadline:
                if self.cancelled():
                    raise InterruptedError('Обработка отменена')
                code = self.process.poll()
                if code is not None:
                    self._failure(code)
                    raise RuntimeError('Не удалось запустить автоматический обмен Antigravity; проверьте runner.log')
                if self._state().get('status') in ('waiting','processing','waiting_quota'):
                    self.monitor = threading.Thread(target=self._watch,daemon=True)
                    self.monitor.start()
                    return self
                time.sleep(.1)
            raise RuntimeError('Antigravity не подтвердил запуск автоматического обмена за 15 секунд')
        except BaseException:
            self.close()
            raise

    def _watch(self):
        while not self.stopping.wait(.5):
            code = self.process.poll()
            if code is None:
                continue
            job = read_json(self.directory/'job.json',{})
            if job.get('status') == 'running':
                self._failure(code)
            return

    def close(self):
        self.stopping.set()
        try:
            if self.process is not None and self.process.poll() is None:
                self.stop_file.write_text('stop','utf-8')
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    # The enclosing worker Job Object is the final descendant
                    # cleanup guarantee; only this owned process is signalled.
                    self.process.terminate()
                    self.process.wait(timeout=5)
        finally:
            if self.monitor:
                self.monitor.join(timeout=2)
            if self.log:
                self.log.close()
            self.stop_file.unlink(missing_ok=True)
