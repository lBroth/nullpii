# SPDX-License-Identifier: Apache-2.0
"""Check-digit algorithms: published reference values, round trips on
generated values, and single-character mutation detection."""

import datetime as dt
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracegen import checkdigits as cd  # noqa: E402
from tracegen import values as V  # noqa: E402

N = 300


class TestLuhn(unittest.TestCase):
    def test_reference(self):
        self.assertTrue(cd.luhn_valid("79927398713"))
        self.assertFalse(cd.luhn_valid("79927398710"))
        self.assertEqual(cd.luhn_check_digit("7992739871"), "3")
        self.assertTrue(cd.luhn_valid("4111 1111 1111 1111"))

    def test_generated_cards(self):
        rng = random.Random(1)
        for brand in ("visa", "mastercard", "amex", "discover"):
            for _ in range(N // 4):
                num, b = V.card_number(rng, brand)
                self.assertTrue(cd.luhn_valid(num), num)
                self.assertEqual(len(num), 15 if brand == "amex" else 16)
                bad = num[:-1] + str((int(num[-1]) + 1) % 10)
                self.assertFalse(cd.luhn_valid(bad))


class TestIban(unittest.TestCase):
    REFERENCE = ["GB82 WEST 1234 5698 7654 32", "DE89 3704 0044 0532 0130 00", "FR14 2004 1010 0505 0001 3M02 606",
                 "IT60 X054 2811 1010 0000 0123 456", "ES91 2100 0418 4502 0005 1332", "NL91 ABNA 0417 1643 00",
                 "BE68 5390 0754 7034", "CH93 0076 2011 6238 5295 7", "AT61 1904 3002 3457 3201"]

    def test_reference(self):
        for iban in self.REFERENCE:
            self.assertTrue(cd.iban_valid(iban), iban)
        self.assertFalse(cd.iban_valid("GB82 WEST 1234 5698 7654 33"))

    def test_national_checks_reference(self):
        self.assertEqual(cd.it_cin("05428", "11101", "000000123456"), "X")
        self.assertEqual(cd.es_dc("2100", "0418", "0200051332"), "45")
        self.assertEqual(cd.fr_rib_key("20041", "01005", "0500013M026"), "06")
        self.assertTrue(cd.nl_account_valid("0417164300"))
        self.assertEqual(cd.be_account_check("5390075470"), "34")

    def test_generated(self):
        rng = random.Random(2)
        for country in ("IT", "DE", "FR", "ES", "NL", "GB", "BE", "PT", "PL", "AT", "CH"):
            for _ in range(N // 10):
                iban = V.iban(rng, country)
                self.assertTrue(iban.startswith(country))
                self.assertTrue(cd.iban_valid(iban), iban)
                self.assertTrue(cd.iban_valid(V.iban_print(iban)))
                i = rng.randrange(4, len(iban))
                ch = iban[i]
                repl = str((int(ch) + 1) % 10) if ch.isdigit() else ("A" if ch != "A" else "B")
                self.assertFalse(cd.iban_valid(iban[:i] + repl + iban[i + 1:]))
                if country == "IT":
                    self.assertEqual(cd.it_cin(iban[5:10], iban[10:15], iban[15:27]), iban[4])
                if country == "ES":
                    self.assertEqual(cd.es_dc(iban[4:8], iban[8:12], iban[14:24]), iban[12:14])
                if country == "FR":
                    self.assertEqual(cd.fr_rib_key(iban[4:9], iban[9:14], iban[14:25]), iban[25:27])
                if country == "NL":
                    self.assertTrue(cd.nl_account_valid(iban[8:18]))
                if country == "PT":
                    self.assertEqual(cd.pt_nib_check(iban[4:23]), iban[23:25])


class TestNationalIds(unittest.TestCase):
    def test_codice_fiscale_reference(self):
        self.assertEqual(cd.codice_fiscale("Rossi", "Mario", dt.date(1980, 1, 1), False, "H501"), "RSSMRA80A01H501U")
        self.assertTrue(cd.cf_valid("RSSMRA80A01H501U"))
        self.assertFalse(cd.cf_valid("RSSMRA80A01H501V"))

    def test_codice_fiscale_rules(self):
        # four or more consonants in the given name: 1st, 3rd and 4th are used; female day + 40
        cf = cd.codice_fiscale("Bianchi", "Francesca", dt.date(1991, 7, 23), True, "F205")
        self.assertEqual(cf[:6], "BNCFNC")
        self.assertEqual(cf[6:11], "91L63")
        self.assertTrue(cd.cf_valid(cf))

    def test_steuer_id(self):
        self.assertTrue(cd.de_steuer_id_valid("86095742719"))
        self.assertFalse(cd.de_steuer_id_valid("86095742718"))
        rng = random.Random(3)
        for _ in range(N):
            self.assertTrue(cd.de_steuer_id_valid(V.steuer_id(rng)))

    def test_nir(self):
        rng = random.Random(4)
        for _ in range(N):
            p = V.make_persona(rng, "fr_FR")
            nir = V.fr_nir(p, rng)
            self.assertTrue(cd.fr_nir_valid(nir), nir)
            self.assertTrue(cd.fr_nir_valid(V.fr_nir_print(nir)))
            self.assertEqual(nir[0], "2" if p.female else "1")
            self.assertEqual(nir[1:5], f"{p.birth.year % 100:02d}{p.birth.month:02d}")
            bad = nir[:-1] + str((int(nir[-1]) + 1) % 10)
            self.assertFalse(cd.fr_nir_valid(bad))

    def test_dni_nie(self):
        self.assertTrue(cd.es_dni_valid("12345678Z"))
        self.assertFalse(cd.es_dni_valid("12345678A"))
        self.assertTrue(cd.es_dni_valid("X1234567L"))
        rng = random.Random(5)
        for _ in range(N):
            self.assertTrue(cd.es_dni_valid(V.es_dni(rng, nie=rng.random() < 0.3)))

    def test_bsn(self):
        self.assertTrue(cd.nl_bsn_valid("111222333"))
        self.assertTrue(cd.nl_bsn_valid("123456782"))
        self.assertFalse(cd.nl_bsn_valid("123456781"))
        rng = random.Random(6)
        for _ in range(N):
            self.assertTrue(cd.nl_bsn_valid(V.nl_bsn(rng)))

    def test_pesel(self):
        self.assertTrue(cd.pl_pesel_valid("44051401359"))
        self.assertFalse(cd.pl_pesel_valid("44051401358"))
        rng = random.Random(7)
        for _ in range(N):
            p = V.make_persona(rng, "pl_PL", min_year=1950, max_year=2008)
            pesel = V.pl_pesel(p, rng)
            self.assertTrue(cd.pl_pesel_valid(pesel))
            self.assertEqual(int(pesel[9]) % 2, 0 if p.female else 1)

    def test_nif_pt(self):
        self.assertTrue(cd.pt_nif_valid("123456789"))
        self.assertFalse(cd.pt_nif_valid("123456780"))
        rng = random.Random(8)
        for _ in range(N):
            self.assertTrue(cd.pt_nif_valid(V.pt_nif(rng)))

    def test_ahv(self):
        self.assertTrue(cd.ch_ahv_valid("756.9217.0769.85"))
        self.assertFalse(cd.ch_ahv_valid("756.9217.0769.86"))
        rng = random.Random(9)
        for _ in range(N):
            self.assertTrue(cd.ch_ahv_valid(V.ch_ahv(rng)))

    def test_nino_ssn(self):
        self.assertTrue(cd.uk_nino_valid("AB123456C"))
        self.assertFalse(cd.uk_nino_valid("QQ123456C"))
        self.assertFalse(cd.uk_nino_valid("GB123456A"))
        self.assertTrue(cd.us_ssn_valid("123-45-6789"))
        for bad in ("666-12-3456", "000-12-3456", "912-12-3456", "123-00-4567", "123-45-0000"):
            self.assertFalse(cd.us_ssn_valid(bad))
        rng = random.Random(10)
        for _ in range(N):
            self.assertTrue(cd.uk_nino_valid(V.uk_nino(rng)))
            self.assertTrue(cd.us_ssn_valid(V.us_ssn(rng)))

    def test_belgian_nrn(self):
        first9 = "930518223"
        self.assertEqual(cd.be_nrn_check(first9, False), f"{97 - int(first9) % 97:02d}")
        self.assertEqual(cd.be_nrn_check("010101123", True), f"{97 - int('2010101123') % 97:02d}")

    def test_national_id_dispatch(self):
        rng = random.Random(11)
        checks = {"codice_fiscale": cd.cf_valid, "steuer_id": cd.de_steuer_id_valid, "nir": cd.fr_nir_valid,
                  "dni": cd.es_dni_valid, "bsn": cd.nl_bsn_valid, "nino": cd.uk_nino_valid, "ssn": cd.us_ssn_valid,
                  "pesel": cd.pl_pesel_valid, "nif": cd.pt_nif_valid}
        from tracegen.lists import LOCALES
        for loc in LOCALES:
            for _ in range(20):
                p = V.make_persona(rng, loc)
                kind, val = V.national_id(p, rng)
                self.assertTrue(checks[kind](val), (loc, kind, val))


class TestVehicleAndMrz(unittest.TestCase):
    def test_vin_reference(self):
        self.assertTrue(cd.vin_valid("1M8GDM9AXKP042788"))
        self.assertTrue(cd.vin_valid("11111111111111111"))
        self.assertFalse(cd.vin_valid("1M8GDM9A1KP042788"))
        self.assertEqual(cd.vin_check_digit("1M8GDM9A0KP042788"), "X")

    def test_vin_generated(self):
        rng = random.Random(12)
        for _ in range(N):
            v = V.vin(rng)
            self.assertEqual(len(v), 17)
            self.assertTrue(cd.vin_valid(v), v)
            self.assertFalse(set(v) & set("IOQ"))

    def test_icao(self):
        self.assertEqual(cd.icao_check_digit("L898902C3"), "6")
        self.assertEqual(cd.icao_check_digit("740812"), "2")
        self.assertEqual(cd.icao_check_digit("120415"), "9")


if __name__ == "__main__":
    unittest.main()
