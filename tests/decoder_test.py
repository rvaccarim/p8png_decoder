import unittest
from src.decoder import extract_code

game_dir = "./0_games/"
expected_dir = "./1_expected/"
decoded_dir = "./2_decoded/"


class TestDecoder(unittest.TestCase):

    def test_plaintext(self):
        self.assertTrue(self.decode("jelpi"))

    def test_oldcompression(self):
        self.assertTrue(self.decode("barp"))
        self.assertTrue(self.decode("trafficworld-3"))
        self.assertTrue(self.decode("jostitle-6"))

    def test_newcompression(self):
        self.assertTrue(self.decode("wolfhunter-0"))
        self.assertTrue(self.decode("superdiscbox-0"))
        self.assertTrue(self.decode("qpong-0"))
        self.assertTrue(self.decode("colourful_life-0"))

    def decode(self, game_name):
        print(game_name)
        with open(f"{expected_dir}{game_name}.txt", mode="r", encoding="utf-8") as f:
            expected_source = f.read()

        decoded_source = extract_code(filename=f"{game_dir}{game_name}.p8.png")

        with open(f"{decoded_dir}{game_name}.txt", mode="w", encoding="utf-8", errors='strict', buffering=1) as f:
            f.write(decoded_source)

        print("=================================================")
        return expected_source == decoded_source


if __name__ == '__main__':
    unittest.main()

