from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LauncherContractTests(unittest.TestCase):
    def test_exactly_one_root_batch_file_exists(self) -> None:
        launchers = sorted(path.name for path in ROOT.glob("*.bat"))
        self.assertEqual(launchers, ["RUN.bat"])

    def test_double_click_defaults_to_start_mode(self) -> None:
        content = (ROOT / "RUN.bat").read_text(encoding="utf-8")
        self.assertIn('if not defined MODE set "MODE=start"', content)
        self.assertIn('if /I "%MODE%"=="start" set "ACTION=start"', content)

    def test_optional_operations_share_the_same_launcher(self) -> None:
        content = (ROOT / "RUN.bat").read_text(encoding="utf-8")
        for mode in ("update", "test", "validate", "release-check"):
            with self.subTest(mode=mode):
                self.assertIn(f'if /I "%MODE%"=="{mode}" set "ACTION={mode}"', content)

    def test_warm_start_skips_dependency_install_when_requirements_are_unchanged(self) -> None:
        content = (ROOT / "RUN.bat").read_text(encoding="utf-8")
        self.assertIn("Get-FileHash requirements.txt -Algorithm SHA256", content)
        self.assertIn(".venv\\deps-installed.sha256", content)
        self.assertIn("pip install --disable-pip-version-check -r requirements.txt", content)


if __name__ == "__main__":
    unittest.main()
