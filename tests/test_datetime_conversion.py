"""Tests for datetime conversion utility."""

import unittest

from scripts.utils.datetime_utils import convert_to_utc8_str


class TestConvertToUTC8Str(unittest.TestCase):
    """Test cases for convert_to_utc8_str function."""

    def test_convert_known_timestamp(self):
        """Test conversion of a known timestamp to UTC+8."""
        result = convert_to_utc8_str(1746538080000)
        self.assertEqual(result, "2025-05-06 21:28:00")

    def test_convert_epoch(self):
        """Test conversion of Unix epoch (0) to UTC+8."""
        result = convert_to_utc8_str(0)
        self.assertEqual(result, "1970-01-01 08:00:00")

    def test_format_consistency(self):
        """Verify format structure matches 'YYYY-MM-DD HH:MM:SS'."""
        result = convert_to_utc8_str(1746538080000)
        self.assertEqual(len(result), 19)
        self.assertEqual(result[4], "-")
        self.assertEqual(result[7], "-")
        self.assertEqual(result[10], " ")
        self.assertEqual(result[13], ":")
        self.assertEqual(result[16], ":")

    def test_negative_timestamp(self):
        """Test conversion of negative timestamp (before epoch)."""
        result = convert_to_utc8_str(-1000)
        self.assertEqual(result, "1970-01-01 07:59:59")

    def test_large_timestamp(self):
        """Test conversion of large timestamp (year 2100+)."""
        result = convert_to_utc8_str(4102444800000)
        self.assertTrue(result.startswith("2100-"))


if __name__ == "__main__":
    unittest.main()
