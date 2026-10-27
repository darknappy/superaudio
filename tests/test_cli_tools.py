"""Pruebas de las herramientas CLI sin cargar el modelo real."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from superaudio import __main__ as M
from superaudio import audition, config as C
from superaudio import quality


class CliToolsTests(unittest.TestCase):
    def setUp(self):
        M._force_utf8_streams()
        self._orig = {
            "TTS_MODEL": C.TTS_MODEL,
            "SPEED": C.SPEED,
            "TOTAL_STEPS": C.TOTAL_STEPS,
            "ENABLE_NUMBER_NORMALIZATION": C.ENABLE_NUMBER_NORMALIZATION,
            "ENABLE_EXPRESSION_CUES": C.ENABLE_EXPRESSION_CUES,
        }

    def tearDown(self):
        for key, value in self._orig.items():
            setattr(C, key, value)

    def test_audition_without_book(self):
        with mock.patch.object(audition, "run_audition", return_value=True) as run:
            rc = M.main([
                "--audition",
                "--audition-voices", "F1,M1",
                "--audition-out", r"C:\tmp\aud",
                "--audition-text", "Texto de prueba",
                "--speed", "1.0",
                "--steps", "6",
            ])
        self.assertEqual(rc, 0)
        run.assert_called_once()
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["voices"], ["F1", "M1"])
        self.assertEqual(kwargs["out_dir"], r"C:\tmp\aud")
        self.assertEqual(kwargs["text"], "Texto de prueba")
        self.assertEqual(kwargs["speed"], 1.0)
        self.assertEqual(kwargs["steps"], 6)

    def test_benchmark_without_book(self):
        with mock.patch.object(quality, "run_benchmark", return_value=True) as run:
            rc = M.main([
                "--benchmark",
                "--benchmark-out", r"C:\tmp\bench",
                "--voice", "M2",
            ])
        self.assertEqual(rc, 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["out_dir"], r"C:\tmp\bench")
        self.assertEqual(run.call_args.kwargs["voice"], "M2")

    def test_model_and_normalization_flags(self):
        with mock.patch.object(audition, "run_audition", return_value=True):
            rc = M.main([
                "--audition",
                "--model", "supertonic-3",
                "--no-numbers",
                "--no-expressions",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(C.TTS_MODEL, "supertonic-3")
        self.assertFalse(C.ENABLE_NUMBER_NORMALIZATION)
        self.assertFalse(C.ENABLE_EXPRESSION_CUES)

    def test_invalid_model_is_rejected(self):
        rc = M.main(["--audition", "--model", "modelo-inventado"])
        self.assertEqual(rc, 2)

    def test_steps_out_of_range_is_rejected(self):
        rc = M.main(["--audition", "--steps", "13"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
