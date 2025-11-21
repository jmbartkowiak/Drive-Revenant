import unittest

from app_config import AppConfig
from app_core import FakeClock, Scheduler
from app_types import OperationType


class SchedulerSpacingTests(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig(
            install_id="test-install",
            jitter_sec=1,
            scheduler_min_read_spacing_ms=600,
            scheduler_min_write_spacing_ms=1200,
        )
        self.clock = FakeClock(start_time=0.0)
        self.scheduler = Scheduler(self.config, clock=self.clock)

    def test_apply_global_spacing_uses_operation_type(self):
        read_candidate = self.scheduler._apply_global_spacing(0.3, OperationType.READ)
        self.assertEqual(read_candidate, 0.75)
        self.assertEqual(self.scheduler._last_global_write_at, 0.0)

        self.clock.advance(0.1)
        second_read_candidate = self.scheduler._apply_global_spacing(0.5, OperationType.READ)
        self.assertEqual(second_read_candidate, 1.5)

        self.clock.advance(0.1)
        write_candidate = self.scheduler._apply_global_spacing(0.4, OperationType.WRITE)
        self.assertEqual(write_candidate, 1.25)

        self.assertEqual(self.scheduler._last_global_read_at, second_read_candidate)
        self.assertEqual(self.scheduler._last_global_write_at, write_candidate)

    def test_plan_next_operation_respects_operation_type(self):
        self.clock.advance(5.0)
        planned_time = self.scheduler.plan_next_operation(
            "X:",
            base_interval_sec=1.0,
            operation_type=OperationType.WRITE,
        )

        self.assertGreater(self.scheduler._last_global_write_at, 0.0)
        self.assertGreaterEqual(self.scheduler._last_global_write_at, planned_time)
        self.assertEqual(self.scheduler._last_global_read_at, 0.0)


if __name__ == "__main__":
    unittest.main()
