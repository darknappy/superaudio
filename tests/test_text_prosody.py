"""Pruebas de normalización, segmentación y prosodia de texto."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from superaudio import config as C
from superaudio import text as T


class TextProsodyTests(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "STYLE_PAUSES_MS": dict(C.STYLE_PAUSES_MS),
            "SENTENCE_GAP_MS": C.SENTENCE_GAP_MS,
            "SENTENCE_MAX_CHARS": C.SENTENCE_MAX_CHARS,
            "MAX_PARAGRAPHS_PER_BLOCK": C.MAX_PARAGRAPHS_PER_BLOCK,
            "ENABLE_NUMBER_NORMALIZATION": C.ENABLE_NUMBER_NORMALIZATION,
            "ENABLE_EXPRESSION_CUES": C.ENABLE_EXPRESSION_CUES,
        }
        C.STYLE_PAUSES_MS = {
            "narracion": 500, "dialogo": 400, "pensamiento": 650,
        }
        C.SENTENCE_GAP_MS = 300
        C.SENTENCE_MAX_CHARS = 220
        C.MAX_PARAGRAPHS_PER_BLOCK = 2
        T.clear_book_pronunciation()

    def tearDown(self):
        for key, value in self._orig.items():
            setattr(C, key, value)
        T.clear_book_pronunciation()

    def test_spanish_abbreviations(self):
        result = T.clean(
            "El Dr. Ruiz y la Sra. Gómez llegaron con el Sr. Pérez. "
            "Trajeron mapas, brújulas, etc., por si acaso."
        )
        self.assertIn("Doctor Ruiz", result)
        self.assertIn("Señora Gómez", result)
        self.assertIn("Señor Pérez", result)
        self.assertIn("etcétera", result)
        self.assertNotIn("Dr.", result)
        self.assertNotIn("Sra.", result)

    def test_chapter_marker_keeps_number_for_metadata(self):
        self.assertEqual(T.clean("Cap. 1"), "Capítulo 1")
        self.assertEqual(T.clean("Capítulo 12"), "Capítulo 12")

    @unittest.skipUnless(T._num2words is not None, "num2words no está instalado")
    def test_numbers_dates_times_and_units(self):
        result = T.clean(
            "En 1984, el 25% de los habitantes pagaba 12,50 € "
            "y el viaje duraba 2 h."
        )
        self.assertIn("mil novecientos ochenta y cuatro", result)
        self.assertIn("veinticinco por ciento", result)
        self.assertIn("doce coma cincuenta euros", result)
        self.assertIn("dos horas", result)
        self.assertIn("veinte dólares", T.clean("20 $"))
        self.assertIn("veinte libras", T.clean("20 £"))

        self.assertIn("doce de marzo de dos mil veinticuatro",
                      T.clean("12/03/2024"))
        self.assertIn("nueve y media", T.clean("9:30"))

    def test_expression_cues_and_tag_whitelist(self):
        result = T.clean("[ríe] No puedo creerlo!! <b>Texto</b> <laugh>")
        self.assertIn("<laugh>", result)
        self.assertIn("!!", result)
        self.assertNotIn("<b>", result)
        self.assertNotIn("</b>", result)

    def test_expression_cues_can_be_disabled(self):
        C.ENABLE_EXPRESSION_CUES = False
        result = T.clean("[ríe] No puedo creerlo.")
        self.assertIn("[ríe]", result)
        self.assertNotIn("<laugh>", result)

    def test_scene_break_token_survives_cleaning(self):
        self.assertEqual(T.clean("***"), T.SCENE_BREAK_TOKEN)
        self.assertEqual(T.clean("* * *"), T.SCENE_BREAK_TOKEN)

    def test_split_sentences_protects_abbreviation(self):
        parts = T.split_sentences("El Dr. Ruiz llegó. Luego se fue.")
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0], "El Dr. Ruiz llegó.")

    def test_long_text_is_split_without_losing_content(self):
        long_text = (
            "Cuando llegó al pueblo, después de caminar durante horas bajo "
            "la lluvia, comprendió que nada volvería a ser como antes, y "
            "aunque intentó sonreír, solo pudo mirar el horizonte."
        )
        parts = T.split_long_text(long_text, 80)
        self.assertGreater(len(parts), 1)
        self.assertEqual(" ".join(parts), long_text)

    def test_dialogue_turns_are_separate_blocks(self):
        blocks = T.build_blocks([
            "—Hola —dijo Ana.",
            "—Adiós —respondió Luis.",
        ])
        self.assertEqual(len(blocks), 2)
        self.assertEqual([b["style"] for b in blocks], ["dialogo", "dialogo"])
        self.assertEqual(blocks[-1]["pause_after_ms"], 400)

    def test_leading_tag_does_not_hide_dialogue(self):
        blocks = T.build_blocks(["<laugh> —Hola —dijo Ana."])
        self.assertEqual(blocks[0]["style"], "dialogo")

    def test_opening_mark_after_tag_and_dash(self):
        self.assertIn("—¿Hola?", T.clean("<laugh> —Hola?"))
        self.assertIn('"¿Hola?"', T.clean('<laugh> "Hola?"'))

    def test_narration_is_grouped_but_limited(self):
        blocks = T.build_blocks([
            "Narración uno.",
            "Narración dos.",
            "Narración tres.",
        ])
        self.assertEqual(len(blocks), 2)
        self.assertIn("\n\n", blocks[0]["text"])
        self.assertEqual(blocks[-1]["pause_after_ms"], 500)

    def test_scene_break_uses_long_pause(self):
        blocks = T.build_blocks([
            "Hola.",
            T.SCENE_BREAK_TOKEN,
            "Adiós.",
        ])
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["pause_after_ms"], C.SILENCE_SCENE_BREAK_MS)
        self.assertEqual(blocks[1]["pause_after_ms"], 500)

    def test_long_paragraph_uses_sentence_gap(self):
        C.SENTENCE_MAX_CHARS = 70
        long_text = (
            "Cuando llegó al pueblo, después de caminar durante horas bajo "
            "la lluvia, comprendió que nada volvería a ser como antes, y "
            "aunque intentó sonreír, solo pudo mirar el horizonte."
        )
        blocks = T.build_blocks([long_text])
        self.assertGreater(len(blocks), 1)
        self.assertEqual(blocks[0]["pause_after_ms"], C.SENTENCE_GAP_MS)
        self.assertEqual(blocks[-1]["pause_after_ms"], 500)

    def test_per_book_pronunciation_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = os.path.join(tmp, "libro.txt")
            with open(book, "w", encoding="utf-8") as f:
                f.write("Nyx")
            pron = os.path.join(tmp, "libro.pronunciation.json")
            with open(pron, "w", encoding="utf-8") as f:
                json.dump({"Nyx": "Nics"}, f)
            T.configure_book_pronunciation(book)
            self.assertEqual(T.clean("Nyx"), "Nics")
            # La palabra completa se respeta: no debe tocar «Nyxes».
            self.assertIn("Nyxes", T.clean("Nyxes"))
            self.assertNotEqual(T.pronunciation_signature(book), "")


if __name__ == "__main__":
    unittest.main()
