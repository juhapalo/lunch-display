import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lunch_display.config import Config


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "kiosk_config", ROOT / "deploy" / "kiosk_config.py"
)
KIOSK_CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KIOSK_CONFIG)


class DeployTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix=".deploy-test-' ")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.app = self.root / "app"
        self.app.mkdir()
        shutil.copytree(ROOT / "deploy", self.app / "deploy")
        (self.app / "lunch_display").mkdir()
        for name in ("__init__.py", "config.py"):
            shutil.copy(ROOT / "lunch_display" / name, self.app / "lunch_display" / name)
        shutil.copy(ROOT / "config.example.json", self.app)
        self.home = self.root / "home"
        self.home.mkdir()
        self.profile = self.home / ".bash_profile"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "commands"
        self.env = dict(
            os.environ, HOME=str(self.home), DISPLAY="",
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            TEST_LOG=str(self.log), TEST_TTY="/dev/tty1",
        )
        self.env.pop("LUNCH_DISPLAY_BROWSER", None)
        self.env.pop("LUNCH_DISPLAY_URL", None)
        for name in (
            "sudo", "raspi-config", "tty", "startx", "xset", "unclutter",
            "matchbox-window-manager", "curl", "surf", "chromium",
            "chromium-browser", "sleep", "apt-cache", "x11vnc",
        ):
            script = self.bin / name
            script.write_text(
                '#!/bin/sh\n'
                'name="${0##*/}"\n'
                'line="$name"\n'
                'for arg do line="$line <$arg>"; done\n'
                'printf "%s\\n" "$line" >> "$TEST_LOG"\n'
                'case "$name" in\n'
                '    tty) printf "%s\\n" "$TEST_TTY" ;;\n'
                '    sudo) if [ "$1" = "tee" ]; then cat >/dev/null; fi ;;\n'
                '    sleep) kill -TERM "$PPID" ;;\n'
                '    apt-cache) exit "${TEST_APT_CACHE_STATUS:-0}" ;;\n'
                'esac\n',
                encoding="utf-8",
            )
            script.chmod(0o755)

    def config(self, data):
        (self.app / "config.json").write_text(json.dumps(data), encoding="utf-8")

    def run_command(self, args):
        return subprocess.run(
            args, cwd=self.home, env=self.env, capture_output=True, text=True,
            timeout=10,
        )

    def helper(self, *args):
        return self.run_command([
            "python3", str(self.app / "deploy" / "kiosk_config.py"), *args
        ])

    def install(self):
        return self.run_command(["sh", str(self.app / "deploy" / "install.sh")])

    def kiosk(self):
        return self.run_command(["sh", str(self.app / "deploy" / "kiosk.sh")])

    def vnc(self):
        self.env["RUNTIME_DIRECTORY"] = str(self.root / "run")
        (self.root / "run").mkdir(mode=0o700, exist_ok=True)
        return self.run_command(["sh", str(self.app / "deploy" / "vnc.sh")])

    def commands(self):
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def login(self):
        self.env["TEST_PROFILE"] = str(self.profile)
        return self.run_command([
            "bash", "--noprofile", "--norc", "-c",
            '. "$TEST_PROFILE"; status=$?; echo "continued:$status"',
        ])

    def legacy_block(self):
        return (
            '# lunch-display kiosk\n'
            'if [ -z "${DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ]; then\n'
            '    exec startx "%s/deploy/kiosk.sh" -- -nocursor\n'
            'fi\n' % self.app
        )

    def test_config_defaults_explicit_flags_and_save(self):
        self.assertIs(Config(None).get("frontend_browser_enabled"), True)
        for data, expected in (
            ({}, True), ({"frontend_browser_enabled": True}, True),
            ({"frontend_browser_enabled": False}, False),
        ):
            with self.subTest(data=data):
                self.config(data)
                config = Config(str(self.app / "config.json"))
                self.assertIs(config.get("frontend_browser_enabled"), expected)
                config.set_rotation([{"url": "dashboard", "duration": 10}])
                self.assertIs(
                    Config(str(self.app / "config.json")).get("frontend_browser_enabled"),
                    expected,
                )
                result = self.helper("browser-enabled")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), str(expected).lower())

    def test_strict_boolean_validation(self):
        for value in ("false", "true", "", 0, 1, None, [], {}):
            with self.subTest(value=value):
                self.config({"frontend_browser_enabled": value})
                with self.assertRaisesRegex(ValueError, "must be a JSON boolean"):
                    Config(str(self.app / "config.json"))
                for result in (self.helper("browser-enabled"), self.kiosk(), self.install()):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("must be a JSON boolean", result.stderr)
                self.assertEqual(self.commands(), "")
                self.assertFalse(self.profile.exists())

    def test_invalid_and_unreadable_config_fail_before_browser_or_install(self):
        for content in ("{", "[]", "null", '"false"', '{"x": NaN, "frontend_browser_enabled": null}'):
            with self.subTest(content=content):
                (self.app / "config.json").write_text(content, encoding="utf-8")
                for result in (self.helper("browser-enabled"), self.kiosk(), self.install()):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("cannot load", result.stderr)
                    self.assertIn(str(self.app / "config.json"), result.stderr)
                self.assertEqual(self.commands(), "")
        (self.app / "config.json").unlink()
        result = self.kiosk()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot load", result.stderr)
        (self.app / "config.json").mkdir()
        for result in (self.kiosk(), self.install()):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot load", result.stderr)
        self.assertEqual(self.commands(), "")
        with patch.object(KIOSK_CONFIG, "APP_DIR", self.app):
            with patch.object(Path, "open", side_effect=PermissionError("permission denied")):
                with self.assertRaisesRegex(ValueError, "permission denied"):
                    KIOSK_CONFIG.browser_enabled()

    def test_disabled_direct_kiosk_has_no_side_effects_from_other_cwd(self):
        self.config({"frontend_browser_enabled": False})
        # The caller's configuration must not override the application's setting.
        (self.home / "config.json").write_text('{"frontend_browser_enabled": true}')
        result = self.kiosk()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), "")

    def test_enabled_direct_kiosk_defaults_and_browser_overrides(self):
        for data, browser in (
            ({}, "surf"), ({"frontend_browser_enabled": True}, "chromium"),
            ({"frontend_browser_enabled": True}, "chromium-browser"),
            ({}, ""),
        ):
            with self.subTest(data=data, browser=browser):
                self.config(data)
                self.env["LUNCH_DISPLAY_BROWSER"] = browser
                browser = browser or "chromium-browser"
                self.env["LUNCH_DISPLAY_URL"] = "http://localhost:9090/custom"
                self.log.unlink(missing_ok=True)
                result = self.kiosk()
                # The mocked sleep terminates this normally infinite restart loop.
                self.assertEqual(result.returncode, -15, result.stderr)
                commands = self.commands()
                self.assertIn("xset <s> <off>", commands)
                self.assertIn("xset <-dpms>", commands)
                self.assertIn("matchbox-window-manager", commands)
                self.assertIn("curl <-fs> <-o> </dev/null> <http://localhost:9090/custom>", commands)
                self.assertIn(browser + " <", commands)
                self.assertIn("<http://localhost:9090/custom>", commands)
                if browser != "surf":
                    for flag in (
                        "--kiosk", "--noerrdialogs", "--disable-infobars",
                        "--disable-session-crashed-bubble",
                        "--check-for-update-interval=31536000",
                        "--remote-debugging-port=9222",
                    ):
                        self.assertIn("<%s>" % flag, commands)
                    self.assertNotIn("<--incognito>", commands)

    def test_kiosk_default_urls_and_extra_flags(self):
        self.config({})
        for browser, url in (
            ("", "http://localhost:8080/dashboard"), ("surf", "http://localhost:8080/"),
        ):
            with self.subTest(browser=browser):
                self.env["LUNCH_DISPLAY_BROWSER"] = browser
                self.env["LUNCH_DISPLAY_CHROMIUM_FLAGS"] = "--extra-one --extra-two"
                self.log.unlink(missing_ok=True)
                result = self.kiosk()
                self.assertEqual(result.returncode, -15, result.stderr)
                commands = self.commands()
                self.assertIn("curl <-fs> <-o> </dev/null> <%s>" % url, commands)
                browser_line = [line for line in commands.splitlines()
                                if line.startswith((browser or "chromium-browser") + " <")][0]
                self.assertTrue(browser_line.endswith("<%s>" % url))
                if browser == "surf":
                    self.assertNotIn("--extra-one", commands)
                else:
                    self.assertIn("<--extra-one> <--extra-two>", browser_line)

    def test_kiosk_clears_crashed_profile_state(self):
        self.config({})
        preferences = self.home / ".config" / "lunch-display-chromium" / "Default" / "Preferences"
        preferences.parent.mkdir(parents=True)
        preferences.write_text('{"profile":{"exit_type":"Crashed","exited_cleanly":false}}')
        result = self.kiosk()
        self.assertEqual(result.returncode, -15, result.stderr)
        self.assertEqual(
            preferences.read_text(),
            '{"profile":{"exit_type":"Normal","exited_cleanly":true}}',
        )

    def test_disabled_fresh_install_only_installs_service(self):
        self.config({"frontend_browser_enabled": False})
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        self.assertIn("sudo <apt-get> <install> <-y> <--no-install-recommends> <python3> <curl>", commands)
        self.assertIn("sudo <systemctl> <enable> <--now> <lunch-display.service>", commands)
        for package in ("xserver", "xinit", "matchbox", "chromium", "unclutter",
                        "fonts-", "x11vnc", "lunch-display-vnc"):
            self.assertNotIn(package, commands)
        self.assertNotIn("raspi-config", commands)
        self.assertFalse(self.profile.exists())

    def test_disabled_install_preserves_unrelated_profile(self):
        original = "# user's own kiosk\nprintf 'hello'\n# lunch-display kiosk note\n"
        self.profile.write_text(original)
        self.config({"frontend_browser_enabled": False})
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.profile.read_text(), original)

    def test_legacy_migration_is_idempotent_and_disabled_login_continues(self):
        prefix = "export UNRELATED=kept\n"
        suffix = "echo unrelated-suffix\n"
        self.profile.write_text(prefix + self.legacy_block() + suffix)
        self.config({"frontend_browser_enabled": False})
        for _ in range(2):
            result = self.install()
            self.assertEqual(result.returncode, 0, result.stderr)
        content = self.profile.read_text()
        self.assertTrue(content.startswith(prefix))
        self.assertTrue(content.endswith(suffix))
        self.assertEqual(content.count("# lunch-display kiosk\n"), 1)
        self.assertEqual(content.count("# end lunch-display kiosk\n"), 1)
        result = self.login()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("continued:0", result.stdout)
        self.assertIn("unrelated-suffix", result.stdout)
        self.assertNotIn("startx", self.commands())
        self.assertNotIn("raspi-config", self.commands())
        self.assertEqual(self.helper("install-profile", str(self.profile)).returncode, 0)
        self.assertEqual(self.profile.read_text(), content)
        # The installed guard re-reads configuration at login; reinstall is unnecessary.
        self.config({"frontend_browser_enabled": True})
        result = self.login()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("continued:", result.stdout)
        self.assertIn("startx <%s/deploy/kiosk.sh> <--> <-nocursor>" % self.app, self.commands())

    def test_enabled_fresh_install_and_reinstall(self):
        self.profile.write_text("export UNRELATED=kept")  # No final newline.
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.app / "config.json").exists())
        self.assertIs(json.loads((self.app / "config.json").read_text())["frontend_browser_enabled"], True)
        commands = self.commands()
        self.assertIn("<xserver-xorg> <xinit> <x11-xserver-utils>", commands)
        self.assertIn("<matchbox-window-manager> <unclutter> <chromium-browser>", commands)
        self.assertNotIn("surf", commands)
        self.assertIn("sudo <apt-get> <install> <-y> <--no-install-recommends> <x11vnc>", commands)
        self.assertIn("sudo <tee> </etc/systemd/system/lunch-display-vnc.service>", commands)
        self.assertIn("sudo <systemctl> <enable> <lunch-display-vnc.service>", commands)
        self.assertIn("vnc_password is empty", result.stderr)
        self.assertIn("sudo <raspi-config> <nonint> <do_boot_behaviour> <B2>", commands)
        content = self.profile.read_text()
        self.assertTrue(content.startswith("export UNRELATED=kept\n"))
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.profile.read_text(), content)
        self.config({})
        result = self.login()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("continued:", result.stdout)
        self.assertIn("startx", self.commands())

    def test_install_chromium_package_name_and_vnc_disabled(self):
        self.config({"vnc_enabled": False})
        self.env["TEST_APT_CACHE_STATUS"] = "100"
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        self.assertIn("<unclutter> <chromium> <fonts-dejavu-core>", commands)
        self.assertNotIn("x11vnc", commands)
        self.assertNotIn("sudo <tee> </etc/systemd/system/lunch-display-vnc.service>", commands)
        self.assertNotIn("vnc_password is empty", result.stderr)

    def test_vnc_service_template(self):
        unit = (ROOT / "deploy" / "lunch-display-vnc.service").read_text()
        self.assertIn("ExecStart=/bin/sh @APP_DIR@/deploy/vnc.sh", unit)
        self.assertIn("User=@USER@", unit)
        self.assertIn("RuntimeDirectoryMode=0700", unit)
        self.assertIn("RestartPreventExitStatus=78", unit)
        self.assertIn("WantedBy=multi-user.target", unit)

    def test_vnc_starts_x11vnc_with_password_file(self):
        secret = "Vnc-" + "pass1"
        self.config({"vnc_port": 5901, "vnc_password": secret})
        result = self.vnc()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        password_file = self.root / "run" / "vnc-password"
        self.assertIn(
            "x11vnc <-display> <:0> <-auth> <%s/.Xauthority> <-forever> <-shared> "
            "<-rfbport> <5901> <-passwdfile> <rm:%s>" % (self.home, password_file),
            commands,
        )
        self.assertNotIn(secret, commands)
        self.assertEqual(password_file.read_text(), secret + "\n")
        self.assertEqual(password_file.stat().st_mode & 0o777, 0o600)
        # A stale file is replaced on the next start.
        self.config({"vnc_password": "other"})
        self.assertEqual(self.vnc().returncode, 0)
        self.assertEqual(password_file.read_text(), "other\n")
        self.assertIn("<-rfbport> <5900>", self.commands())

    def test_vnc_requires_private_runtime_directory(self):
        self.config({"vnc_password": "secret"})
        self.env.pop("RUNTIME_DIRECTORY", None)
        self.env.pop("XDG_RUNTIME_DIR", None)
        result = self.run_command(["sh", str(self.app / "deploy" / "vnc.sh")])
        self.assertEqual(result.returncode, 78)
        self.assertIn("RUNTIME_DIRECTORY", result.stderr)
        self.assertEqual(self.commands(), "")

    def test_vnc_disabled_or_without_password_does_not_start(self):
        for data, status in (
            ({"vnc_enabled": False, "vnc_password": "secret"}, 0),
            ({"frontend_browser_enabled": False, "vnc_password": "secret"}, 0),
            ({}, 78),
            ({"vnc_password": "two words"}, 78),
            ({"vnc_password": "#comment"}, 78),
            ({"vnc_password": "a__SKIP__"}, 78),
            ({"vnc_password": "secret", "vnc_port": 0}, 78),
            ({"vnc_password": "secret", "vnc_port": "5900"}, 78),
            ({"vnc_enabled": "true", "vnc_password": "secret"}, 78),
        ):
            with self.subTest(data=data):
                self.config(data)
                result = self.vnc()
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertNotIn("x11vnc", self.commands())
                self.assertFalse((self.root / "run" / "vnc-password").exists())
                if status:
                    self.assertIn("lunch-display kiosk:", result.stderr)

    def test_exact_legacy_migration_preserves_other_marker_sections(self):
        unrelated = (
            "# lunch-display kiosk\n"
            "echo user-custom-kiosk\n"
            "# unrelated user section\n"
        )
        legacy = self.legacy_block().replace(str(self.app), "/old/install/location")
        self.profile.write_text(unrelated + legacy + "echo trailing\n")
        self.config({"frontend_browser_enabled": False})
        self.assertEqual(self.helper("install-profile", str(self.profile)).returncode, 0)
        first = self.profile.read_text()
        self.assertTrue(first.startswith(unrelated))
        self.assertTrue(first.endswith("echo trailing\n"))
        self.assertNotIn("/old/install/location", first)
        self.assertEqual(self.helper("install-profile", str(self.profile)).returncode, 0)
        self.assertEqual(self.profile.read_text(), first)

    def test_profile_errors_do_not_exec_or_exit_login(self):
        self.config({})
        self.assertEqual(self.helper("install-profile", str(self.profile)).returncode, 0)
        for content in ('{"frontend_browser_enabled": "false"}', "{", "[]"):
            with self.subTest(content=content):
                (self.app / "config.json").write_text(content)
                result = self.login()
                self.assertIn("continued:1", result.stdout)
                self.assertIn("lunch-display kiosk:", result.stderr)
                self.assertNotIn("startx", self.commands())
        (self.app / "config.json").unlink()
        result = self.login()
        self.assertIn("continued:1", result.stdout)
        self.assertIn("cannot load", result.stderr)

    def test_profile_only_starts_on_tty1_without_display(self):
        self.config({})
        self.assertEqual(self.helper("install-profile", str(self.profile)).returncode, 0)
        for display, tty in ((":0", "/dev/tty1"), ("", "/dev/pts/0")):
            with self.subTest(display=display, tty=tty):
                self.env.update(DISPLAY=display, TEST_TTY=tty)
                result = self.login()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("continued:0", result.stdout)
                self.assertNotIn("startx", self.commands())


if __name__ == "__main__":
    unittest.main()
