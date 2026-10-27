"""Pruebas de pulido, normalización y métricas de audio."""
import array
import math
import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from superaudio import audio, config as C
from superaudio import quality


def write_wav(path, samples, rate=44100):
    data = array.array("h", samples)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(data.tobytes())


def read_wav(path):
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.getnframes()
        raw = wf.readframes(frames)
    data = array.array("h")
    data.frombytes(raw)
    return rate, frames, data


def tone(rate=44100, seconds=0.3, amplitude=0.25):
    return [
        int(amplitude * 32767 * math.sin(2 * math.pi * 440 * i / rate))
        for i in range(int(rate * seconds))
    ]


class AudioQualityTests(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "TRIM_TTS_EDGES": C.TRIM_TTS_EDGES,
            "EDGE_FADE_MS": C.EDGE_FADE_MS,
            "LOUDNORM_TARGET_I": C.LOUDNORM_TARGET_I,
            "LOUDNORM_TARGET_TP": C.LOUDNORM_TARGET_TP,
        }
        C.TRIM_TTS_EDGES = True
        C.EDGE_FADE_MS = 8

    def tearDown(self):
        for key, value in self._orig.items():
            setattr(C, key, value)

    def test_loudnorm_filter_uses_audiobook_target(self):
        spec = audio._loudnorm_filter()
        self.assertIn("I=-18", spec)
        self.assertIn("TP=-3", spec)
        self.assertIn("LRA=11", spec)

    def test_polish_trims_edges_and_applies_fade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "block.wav"
            samples = [0] * 4410 + tone() + [0] * 4410
            write_wav(path, samples)
            self.assertTrue(audio.polish_wav(str(path)))
            rate, frames, data = read_wav(path)
            self.assertLess(frames, len(samples))
            self.assertEqual(data[0], 0)
            self.assertEqual(data[-1], 0)
            self.assertGreater(max(abs(s) for s in data), 1000)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg no está disponible")
    def test_normalize_wav_is_two_pass_and_near_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "tone.wav"
            target = Path(tmp) / "normalized.wav"
            write_wav(source, tone(seconds=1.0), rate=44100)
            audio.normalize_wav(str(source), str(target))
            self.assertTrue(target.exists())
            measured = audio._measure_loudness(str(target))
            self.assertIsNotNone(measured)
            self.assertAlmostEqual(float(measured["input_i"]), -18.0, delta=2.0)

    def test_quality_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metric.wav"
            write_wav(path, [0] * 4410 + tone() + [0] * 4410)
            metrics = quality.analyze_wav(str(path), "texto de prueba")
            self.assertGreater(metrics["duration_s"], 0)
            self.assertEqual(metrics["sample_rate"], 44100)
            self.assertEqual(metrics["clipped_samples"], 0)
            self.assertGreater(metrics["silence_ratio"], 0)
            self.assertIsNotNone(metrics["chars_per_second"])


if __name__ == "__main__":
    unittest.main()
