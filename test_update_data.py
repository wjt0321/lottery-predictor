import unittest

import update_data


class UpdateDataTests(unittest.TestCase):
    def test_build_date_range_orders_old_to_new(self):
        records = [
            {"period": "2026045", "date": "2026-04-21"},
            {"period": "2026044", "date": "2026-04-19"},
            {"period": "2026043", "date": "2026-04-17"},
        ]

        date_range = update_data.build_date_range(records)

        self.assertEqual(date_range, "2026-04-17 至 2026-04-21")


if __name__ == "__main__":
    unittest.main()
