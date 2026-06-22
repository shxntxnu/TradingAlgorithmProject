import os
import unittest
import tempfile
import pandas as pd
from datetime import datetime, timedelta

from data.storage.store import LocalParquetStore
from data.validation.pit_validation import validate_ohlcv_schema, check_pit_integrity

class TestPointInTime(unittest.TestCase):
    """Test suite verifying point-in-time correctness and schema validation."""
    
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.store = LocalParquetStore(root_dir=self.test_dir.name)
        
        # Build standard mock data
        self.dates = [
            datetime(2026, 1, 1),
            datetime(2026, 1, 2),
            datetime(2026, 1, 3),
            datetime(2026, 1, 4),
        ]
        
        self.df = pd.DataFrame({
            'timestamp': self.dates,
            'open': [100.0, 101.0, 102.0, 103.0],
            'high': [101.5, 102.5, 103.5, 104.5],
            'low': [99.5, 100.5, 101.5, 102.5],
            'close': [100.8, 101.8, 102.8, 103.8],
            'volume': [10000, 11000, 12000, 13000],
            # To be strictly PIT, availability is set to timestamp + 1 day at 09:00:00
            'availability_time': [
                datetime(2026, 1, 2, 9, 0),
                datetime(2026, 1, 3, 9, 0),
                datetime(2026, 1, 4, 9, 0),
                datetime(2026, 1, 5, 9, 0),
            ]
        })

    def tearDown(self):
        self.test_dir.cleanup()

    def test_schema_validation(self):
        """Verify that standard schema validation catches invalid prices and volumes."""
        self.assertTrue(validate_ohlcv_schema(self.df))
        
        # Test failure with negative price
        bad_df_price = self.df.copy()
        bad_df_price.loc[0, 'close'] = -5.0
        self.assertFalse(validate_ohlcv_schema(bad_df_price))
        
        # Test failure with missing column
        bad_df_cols = self.df.drop(columns=['volume'])
        self.assertFalse(validate_ohlcv_schema(bad_df_cols))

    def test_pit_integrity_check(self):
        """Verify that check_pit_integrity catches look-ahead availability anomalies."""
        self.assertTrue(check_pit_integrity(self.df))
        
        # Introduce a violation: data available BEFORE event timestamp
        violating_df = self.df.copy()
        violating_df.loc[1, 'availability_time'] = datetime(2026, 1, 1)
        self.assertFalse(check_pit_integrity(violating_df))

    def test_load_data_as_of(self):
        """Verify that loading data as-of a decision date hides future observations."""
        self.store.save_data('TEST', 'ohlcv', self.df)
        
        # As of 2026-01-02 08:00 -> only the first bar (2026-01-01) is available
        # because the 2nd bar isn't available until 2026-01-03 09:00, and 1st is available 2026-01-02 09:00.
        # Wait, the first bar's availability_time is 2026-01-02 09:00.
        # So as of 2026-01-02 08:00, NOTHING should be available!
        df_as_of_2_early = self.store.load_data_as_of('TEST', 'ohlcv', datetime(2026, 1, 2, 8, 0))
        self.assertEqual(len(df_as_of_2_early), 0)
        
        # As of 2026-01-02 10:00 -> Only the first bar (2026-01-01) is available
        df_as_of_2_late = self.store.load_data_as_of('TEST', 'ohlcv', datetime(2026, 1, 2, 10, 0))
        self.assertEqual(len(df_as_of_2_late), 1)
        self.assertEqual(df_as_of_2_late.iloc[0]['timestamp'], pd.Timestamp(2026, 1, 1))
        
        # As of 2026-01-04 10:00 -> Three bars should be available (2026-01-01, 01-02, 01-03)
        df_as_of_4 = self.store.load_data_as_of('TEST', 'ohlcv', datetime(2026, 1, 4, 10, 0))
        self.assertEqual(len(df_as_of_4), 3)

if __name__ == '__main__':
    unittest.main()
