"""Минимальный драйвер браузера поверх Chrome DevTools Protocol.

Нужен, чтобы проверять интерфейс глазами: открыть страницу, нажать кнопку,
дождаться результата и снять экран. Playwright тянуть ради этого незачем —
Chrome уже установлен, а протокол простой.

    python tools/browser.py shot http://127.0.0.1:8000 out.png
    python tools/browser.py script tools/scenarios/demo_flow.py
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge")
    if found:
        return found
    raise RuntimeError("не найден Chrome или Edge — укажите путь в CHROME_CANDIDATES")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Browser:
    """Одна вкладка headless-браузера. Используется как контекстный менеджер."""

    def __init__(self, width: int = 1680, height: int = 1000, headless: bool = True) -> None:
        self.width, self.height = width, height
        self.headless = headless
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="cdp-profile-")
        self.process: subprocess.Popen | None = None
        self.ws: websocket.WebSocket | None = None
        self._id = 0

    # ------------------------------------------------------------ запуск

    def __enter__(self) -> "Browser":
        args = [
            find_chrome(),
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            f"--window-size={self.width},{self.height}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-gpu",
            "--hide-scrollbars",
            # Без этого свежие сборки Chrome отвергают подключение к протоколу
            # отладки с ошибкой 403 из-за проверки Origin.
            "--remote-allow-origins=*",
            "about:blank",
        ]
        if self.headless:
            args.insert(1, "--headless=new")
        self.process = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        target = None
        for _ in range(80):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/list", timeout=1
                ) as response:
                    tabs = json.load(response)
                pages = [t for t in tabs if t.get("type") == "page"]
                if pages:
                    target = pages[0]
                    break
            except Exception:
                time.sleep(0.25)
        if target is None:
            raise RuntimeError("браузер не отозвался на порт отладки")

        self.ws = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=60, max_size=64 * 1024 * 1024
        )
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Log.enable")
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.ws:
                self.ws.close()
        finally:
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            shutil.rmtree(self.profile, ignore_errors=True)

    # ---------------------------------------------------------- протокол

    def send(self, method: str, **params) -> dict:
        assert self.ws is not None
        self._id += 1
        message_id = self._id
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    # -------------------------------------------------------- действия

    def goto(self, url: str, wait_ms: int = 2500) -> None:
        self.send("Page.navigate", url=url)
        self.wait(wait_ms)

    def wait(self, milliseconds: int) -> None:
        time.sleep(milliseconds / 1000)

    def eval(self, expression: str):
        result = self.send(
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=True,
        )
        if result.get("exceptionDetails"):
            text = result["exceptionDetails"].get("exception", {}).get("description")
            raise RuntimeError(f"ошибка в странице: {text}")
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, timeout_s: float = 90, poll_s: float = 0.5) -> bool:
        """Ждёт, пока выражение в странице не станет истинным."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if self.eval(expression):
                    return True
            except RuntimeError:
                pass
            time.sleep(poll_s)
        return False

    def click_text(self, text: str, tag: str = "*") -> bool:
        """Нажимает первый элемент, чей текст совпадает."""
        script = f"""
        (() => {{
          const nodes = [...document.querySelectorAll({tag!r})];
          const found = nodes.find(n => n.textContent.trim() === {text!r}
                                     && n.children.length === 0 || n.textContent.trim() === {text!r});
          const target = nodes.reverse().find(n => n.textContent.trim().startsWith({text!r}));
          const node = found || target;
          if (!node) return false;
          node.click();
          return true;
        }})()
        """
        return bool(self.eval(script))

    def click(self, selector: str, index: int = 0) -> bool:
        script = f"""
        (() => {{
          const nodes = document.querySelectorAll({selector!r});
          if (nodes.length <= {index}) return false;
          nodes[{index}].click();
          return true;
        }})()
        """
        return bool(self.eval(script))

    def text(self, selector: str) -> str:
        return self.eval(
            f"(document.querySelector({selector!r})||{{}}).textContent || ''"
        ) or ""

    def console_errors(self) -> list[str]:
        return self.eval("window.__errors__ || []") or []

    def install_error_trap(self) -> None:
        """Собирает ошибки страницы, чтобы отличать пустой экран от поломки."""
        self.send(
            "Page.addScriptToEvaluateOnNewDocument",
            source="""
            window.__errors__ = [];
            window.addEventListener('error', e =>
              window.__errors__.push(String(e.message)));
            window.addEventListener('unhandledrejection', e =>
              window.__errors__.push('promise: ' + String(e.reason)));
            const orig = console.error;
            console.error = (...a) => { window.__errors__.push(a.map(String).join(' ')); orig(...a); };
            """,
        )

    def screenshot(self, path: str | Path, full_page: bool = False) -> Path:
        params = {"format": "png", "captureBeyondViewport": full_page}
        result = self.send("Page.captureScreenshot", **params)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(result["data"]))
        return target


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    command = sys.argv[1]

    if command == "shot":
        url = sys.argv[2]
        out = sys.argv[3] if len(sys.argv) > 3 else "shot.png"
        with Browser() as browser:
            browser.install_error_trap()
            browser.goto(url, wait_ms=int(os.environ.get("WAIT_MS", 3000)))
            path = browser.screenshot(out)
            errors = browser.console_errors()
        print(f"снимок: {path}")
        if errors:
            print("ошибки страницы:")
            for item in errors:
                print("  -", item)
        return 0

    if command == "script":
        script_path = Path(sys.argv[2])
        namespace: dict = {"Browser": Browser, "__name__": "__cdp_script__"}
        exec(compile(script_path.read_text(encoding="utf-8"), str(script_path), "exec"), namespace)
        return 0

    print(f"неизвестная команда: {command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
