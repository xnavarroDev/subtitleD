"""Windows companion UI. The packaged build includes Python and the connector sources.

Docker remains the processing runtime; no Python or terminal is needed by end users.
Importing this module never changes the system or starts processing.
"""

import argparse
import json
import os
import queue
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import webbrowser

import local_connector as launcher


def parse_link(value):
    """Untrusted URL handlers may supply only a website, never local commands."""
    parsed = urlsplit(value)
    if (len(value) > 2048 or parsed.scheme != "subtitled" or parsed.netloc != "connect"
            or parsed.path not in {"", "/"} or parsed.fragment):
        raise ValueError("This is not a SubtitleD connection link.")
    query = parse_qs(parsed.query, strict_parsing=True)
    if set(query) != {"origin"} or len(query["origin"]) != 1:
        raise ValueError("The connection link must contain one website address.")
    return launcher.trusted_origin(query["origin"][0])


def companion_home():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "SubtitleD"


def configure_runtime(home, bundle=None):
    """Copy only shipped assets; updates preserve all user storage and settings."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    if bundle is not None:
        bundle = Path(bundle)
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        runtime = home / "runtime"
        for name in manifest["files"]:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or "storage" in relative.parts or relative.name.startswith(".env"):
                raise ValueError("Invalid companion runtime manifest.")
            source, target = bundle / relative, runtime / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or source.read_bytes() != target.read_bytes():
                shutil.copyfile(source, target)
        launcher.ROOT = runtime
    launcher.CONFIG = home / ".env.connector"
    launcher.SETUP_FILE = home / "subtitled-setup.json"
    if bundle is not None:
        values = launcher.read_config()
        if manifest.get("image"):
            values["CONNECTOR_IMAGE"] = manifest["image"]
        else:
            values.pop("CONNECTOR_IMAGE", None)
        launcher.write_config(values)
    return home


def connection_url(values):
    origin = launcher.trusted_origin(values["CORS_ORIGINS"])
    request = Request(
        launcher.connector_address(values) + "/connector/pairing-ticket",
        data=json.dumps({"origin": origin}).encode(), method="POST",
        headers={"Authorization": "Bearer " + values["CONNECTOR_TOKEN"], "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        ticket = json.load(response)["ticket"]
    # Fragments stay out of HTTP requests, server logs, and Referer headers.
    return origin + "/#" + urlencode({"companion_ticket": ticket, "connector": launcher.connector_address(values)})


def worker_command(home, log_path, args):
    prefix = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]
    return prefix + ["--home", str(home), "--worker-log", str(log_path), "--worker", *args]


def bundle_path():
    return Path(sys._MEIPASS) / "runtime" if getattr(sys, "frozen", False) else None


class Companion:
    def __init__(self, home, requested_origin=None):
        import tkinter as tk
        from tkinter import ttk, messagebox

        self.tk, self.messagebox = tk, messagebox
        self.home, self.process, self.action = home, None, None
        self.events, self.tray = queue.Queue(), None
        self.window = tk.Tk()
        self.window.title("SubtitleD Companion")
        self.window.geometry("660x640")
        self.window.minsize(550, 570)
        self.window.configure(bg="#fcfcfa")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#fcfcfa")
        style.configure("TLabel", background="#fcfcfa", foreground="#252c29", font=("Segoe UI", 10))
        style.configure("TButton", padding=8, font=("Segoe UI", 10))
        style.configure("Mint.TButton", background="#4ddd9d", foreground="#081b12")
        frame = ttk.Frame(self.window, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="S:D  Companion", font=("Consolas", 23, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Local processing. One place to start and connect.").pack(anchor="w", pady=(4, 20))
        values = launcher.read_config()
        self.origin = tk.StringVar(value=values.get("CORS_ORIGINS", launcher.DEFAULT_ORIGIN))
        self.model = tk.StringVar(value=values.get("WHISPER_MODEL_SIZE", "small"))
        ttk.Label(frame, text="SubtitleD website").pack(anchor="w")
        self.website_input = ttk.Entry(frame, textvariable=self.origin)
        self.website_input.pack(fill="x", pady=(5, 12))
        ttk.Label(frame, text="Transcription model (small is the balanced CPU default)").pack(anchor="w")
        self.model_input = ttk.Combobox(frame, textvariable=self.model, values=sorted(launcher.MODELS), state="readonly")
        self.model_input.pack(fill="x", pady=(5, 12))
        self.status = tk.StringVar(value="Ready to start. Docker Desktop must be installed.")
        ttk.Label(frame, textvariable=self.status, wraplength=590).pack(anchor="w", pady=(0, 8))
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 12))
        self.start_button = ttk.Button(frame, text="Start and connect", style="Mint.TButton", command=self.start)
        self.start_button.pack(fill="x")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=8)
        self.prepare_button = ttk.Button(actions, text="Prepare transcription", command=lambda: self.run("prepare"))
        self.prepare_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="Stop processing", command=self.stop)
        self.stop_button.pack(side="right")
        links = ttk.Frame(frame)
        links.pack(fill="x", pady=(0, 8))
        ttk.Button(links, text="Install Docker Desktop", command=lambda: webbrowser.open("https://www.docker.com/products/docker-desktop/")).pack(side="left")
        ttk.Button(links, text="Set up translation", command=self.translation).pack(side="right")
        ttk.Label(frame, text="First startup downloads processing tools. Models download on first use.\nClosing this window leaves processing running; use Stop to shut it down.", wraplength=590).pack(anchor="w", pady=(0, 12))
        self.log = tk.Text(frame, height=9, bg="#f1f4f1", fg="#36453c", font=("Consolas", 9), relief="flat", state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log_path = home / "companion.log"
        self.offset = 0
        self.start_tray()
        self.window.after(300, self.poll)
        if requested_origin:
            self.window.after(100, lambda: self.handle_origin(requested_origin))

    def handle_origin(self, origin):
        self.window.deiconify()
        self.window.lift()
        if self.process:
            self.messagebox.showinfo("Already working", "Wait for the current step to finish, then click Start and connect.")
            return
        self.origin.set(origin)
        # URL handlers never silently authorize a site or start its tools.
        if self.messagebox.askyesno("Connect this website?", f"Allow {origin} to use SubtitleD on this device?\n\nThis website will be able to access your local SubtitleD projects."):
            self.start(approved=True)

    def start(self, approved=False):
        if self.process:
            return
        try:
            origin = launcher.trusted_origin(self.origin.get())
            values = launcher.read_config()
            if not approved and values.get("CORS_ORIGINS") != origin:
                if not self.messagebox.askyesno("Approve website", f"Allow {origin} to access your local SubtitleD projects?"):
                    return
            if not shutil.which("docker"):
                raise launcher.SetupError("Install Docker Desktop using the button below, then reopen the companion after installation.")
            # Start an already installed Docker Desktop, without elevating or installing it.
            docker_app = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
            if docker_app.exists():
                subprocess.Popen([str(docker_app)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.run("start", "--origin", origin, "--whisper-model", self.model.get(), "--no-browser", "--quiet-pairing", "--auto-port", "--project-name", values.get("CONNECTOR_PROJECT_NAME", "subtitled-companion"))
        except (ValueError, OSError, launcher.SetupError, argparse.ArgumentTypeError) as exc:
            self.messagebox.showerror("Setup needs attention", str(exc))

    def run(self, action, *args):
        if self.process:
            return
        self.log_path.write_text("", encoding="utf-8")
        self.offset = 0
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.action = action
        try:
            self.process = subprocess.Popen(worker_command(self.home, self.log_path, [action, *args]), cwd=launcher.ROOT,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.messagebox.showerror("Could not start", str(exc))
            return
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.prepare_button.configure(state="disabled")
        self.website_input.configure(state="disabled")
        self.model_input.configure(state="disabled")
        self.progress.start(12)
        self.status.set({"start": "Starting local processing. First setup can take several minutes…", "prepare": "Downloading and checking the transcription model…", "prepare-translation": "Downloading and preparing the NLLB backup translator. This can take several minutes…", "stop": "Stopping local processing. Your files will be kept."}[action])

    def stop(self):
        if self.messagebox.askyesno("Stop local processing?", "Active transcription, translation, or rendering will be interrupted. Stop anyway?"):
            self.run("stop")

    def translation(self):
        answer = self.messagebox.askyesnocancel("Set up translation", "Recommended: HY-MT2 through KoboldCpp.\nBackup: NLLB 600M, CPU INT8, independent of KoboldCpp.\n\nInstall the NLLB backup? It downloads the model and conversion files (allow several GB of space). Its CC-BY-NC 4.0 license is non-commercial. No other fallback is installed.\n\nYes: install NLLB backup\nNo: open KoboldCpp downloads\nCancel: keep current setup")
        if answer is True:
            self.run("prepare-translation")
        elif answer is False:
            webbrowser.open("https://github.com/LostRuins/koboldcpp/releases")

    def poll(self):
        while not self.events.empty():
            action = self.events.get_nowait()
            if action == "show":
                self.window.deiconify()
                self.window.lift()
            elif action == "quit":
                if self.process:
                    self.window.deiconify()
                    self.messagebox.showinfo("Setup in progress", "Wait for setup to finish before quitting the companion.")
                else:
                    self.quit()
                    return
        if self.process:
            if self.log_path.exists():
                with self.log_path.open(encoding="utf-8", errors="replace") as stream:
                    stream.seek(self.offset)
                    chunk = stream.read()
                    self.offset = stream.tell()
                if chunk:
                    self.log.configure(state="normal")
                    self.log.insert("end", chunk)
                    self.log.see("end")
                    self.log.configure(state="disabled")
            code = self.process.poll()
            if code is not None:
                self.process = None
                self.progress.stop()
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="normal")
                self.prepare_button.configure(state="normal")
                self.website_input.configure(state="normal")
                self.model_input.configure(state="readonly")
                self.status.set("Ready. Processing stays on your device." if code == 0 else "Setup needs attention. See the details below and retry.")
                if code == 0 and self.action == "start":
                    try:
                        webbrowser.open(connection_url(launcher.read_config()))
                    except (OSError, ValueError, KeyError) as exc:
                        self.status.set("Processing started, but pairing failed. Update the connector or use manual pairing.")
        for path in (self.home / "inbox").glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                path.unlink()
                if data.get("show"):
                    self.window.deiconify()
                    self.window.lift()
                else:
                    self.handle_origin(launcher.trusted_origin(data["origin"]))
            except (OSError, ValueError, KeyError, argparse.ArgumentTypeError):
                path.unlink(missing_ok=True)
        self.window.after(300, self.poll)

    def close(self):
        if self.process:
            self.messagebox.showinfo("Setup in progress", "Leave this window open until the current step finishes.")
            return
        if self.tray:
            self.window.withdraw()
        else:
            self.quit()

    def start_tray(self):
        if sys.platform != "win32":
            return
        try:
            import pystray
            from PIL import Image, ImageDraw
            icon = Image.new("RGB", (64, 64), "#111514")
            draw = ImageDraw.Draw(icon)
            draw.rectangle((5, 5, 58, 58), outline="#4ddd9d", width=3)
            draw.text((15, 23), "S:D", fill="#4ddd9d")
            self.tray = pystray.Icon("SubtitleD", icon, "SubtitleD Companion", menu=pystray.Menu(
                pystray.MenuItem("Open SubtitleD Companion", lambda: self.events.put("show"), default=True),
                pystray.MenuItem("Quit companion (keep processing)", lambda: self.events.put("quit")),
            ))
            threading.Thread(target=self.tray.run, daemon=True).start()
        except ImportError:
            self.tray = None

    def quit(self):
        if self.tray:
            self.tray.stop()
        self.window.destroy()

    def mainloop(self):
        self.window.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="SubtitleD Windows Companion")
    parser.add_argument("--home", type=Path, default=companion_home())
    parser.add_argument("--url", type=parse_link)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--worker-log", type=Path)
    parser.add_argument("--worker", nargs=argparse.REMAINDER)
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if "--url" in raw_args and (len(raw_args) != 2 or raw_args[0] != "--url"):
        parser.error("Website links cannot supply companion command-line options.")
    args = parser.parse_args(raw_args)
    configure_runtime(args.home, bundle_path())
    if args.self_test:
        assert (launcher.ROOT / "docker-compose.local.yml").is_file()
        assert (launcher.ROOT / "backend" / "app" / "connector.py").is_file()
        import tkinter
        assert tkinter.Tcl().eval("info patchlevel")
        (args.home / "self-test.json").write_text(json.dumps({"ok": True, "packaged": bool(getattr(sys, "frozen", False))}))
        return
    if args.worker is not None:
        if not args.worker_log:
            parser.error("Worker requires a log file.")
        with args.worker_log.open("a", encoding="utf-8", buffering=1) as log:
            sys.stdout = sys.stderr = log
            # Docker needs a short grace period after opening Desktop.
            if args.worker and args.worker[0] == "start":
                deadline = time.monotonic() + 90
                attempt = 0
                while time.monotonic() < deadline:
                    if launcher.run_capture(["docker", "info", "--format", "{{.OSType}}"]).returncode == 0:
                        break
                    if attempt == 0:
                        print("Waiting for Docker Desktop to finish starting…", flush=True)
                    time.sleep(2)
                    attempt += 1
            launcher.main(args.worker)
        return
    # Per-user single instance; browser handoffs go to the existing window.
    lock = (args.home / "companion.lock").open("a+b")
    if sys.platform == "win32":
        import msvcrt
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            inbox = args.home / "inbox"
            inbox.mkdir(exist_ok=True)
            pending = inbox / (secrets.token_hex(12) + ".tmp")
            pending.write_text(json.dumps({"origin": args.url} if args.url else {"show": True}), encoding="utf-8")
            pending.replace(pending.with_suffix(".json"))
            return
    try:
        Companion(args.home, args.url).mainloop()
    finally:
        lock.close()


if __name__ == "__main__":
    main()
