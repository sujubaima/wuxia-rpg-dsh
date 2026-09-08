"""将脚本式E2E纳入标准 unittest 发现。"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "e2e_runner.py")


class EngineE2ETest(unittest.TestCase):
    def test_engine_e2e_script(self):
        proc = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True,
                              timeout=120)
        detail = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
        self.assertEqual(proc.returncode, 0, detail[-4000:])
        self.assertIn("全部通过", proc.stdout)


if __name__ == "__main__":
    unittest.main()
