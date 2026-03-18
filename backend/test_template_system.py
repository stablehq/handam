#!/usr/bin/env python3
"""
Test script for template scheduling system
Tests all major components end-to-end
"""
import sys
import os
import asyncio

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.database import SessionLocal
from app.db.models import TemplateSchedule, MessageTemplate, Reservation
from app.scheduler.template_scheduler import TemplateScheduleExecutor
from app.scheduler.schedule_manager import ScheduleManager
from app.scheduler.jobs import scheduler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_template_executor():
    """Test template schedule execution"""
    logger.info("\n=== Testing Template Executor ===")

    db = SessionLocal()
    try:
        # Get a schedule
        schedule = db.query(TemplateSchedule).first()
        if not schedule:
            logger.error("No schedules found in database")
            return False

        logger.info(f"Testing schedule: {schedule.schedule_name}")

        # Create executor
        executor = TemplateScheduleExecutor(db)

        # Preview targets
        logger.info("Previewing targets...")
        targets = executor.preview_targets(schedule)
        logger.info(f"✓ Found {len(targets)} targets")

        if targets:
            logger.info(f"  Sample target: {targets[0]['customer_name']} - {targets[0]['phone']}")

        # Execute schedule (dry run - messages will be mocked)
        logger.info("Executing schedule...")
        result = await executor.execute_schedule(schedule.id)

        if result.get('success'):
            logger.info(f"✓ Execution successful:")
            logger.info(f"  - Sent: {result.get('sent_count', 0)}")
            logger.info(f"  - Failed: {result.get('failed_count', 0)}")
            logger.info(f"  - Target: {result.get('target_count', 0)}")
            return True
        else:
            logger.error(f"✗ Execution failed: {result.get('error')}")
            return False

    except Exception as e:
        logger.error(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_schedule_manager():
    """Test schedule manager"""
    logger.info("\n=== Testing Schedule Manager ===")

    db = SessionLocal()
    try:
        # Create schedule manager
        manager = ScheduleManager(scheduler)

        # Sync schedules
        logger.info("Syncing schedules to APScheduler...")
        manager.sync_all_schedules(db)

        # Get job info
        jobs = manager.get_all_jobs()
        template_jobs = [j for j in jobs if j['id'].startswith('template_schedule_')]

        logger.info(f"✓ Found {len(template_jobs)} template schedule jobs in APScheduler:")
        for job in template_jobs:
            logger.info(f"  - {job['name']}")
            logger.info(f"    Next run: {job.get('next_run', 'N/A')}")

        return len(template_jobs) > 0

    except Exception as e:
        logger.error(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_database_schema():
    """Test database schema"""
    logger.info("\n=== Testing Database Schema ===")

    db = SessionLocal()
    try:
        # Check template schedules
        schedules = db.query(TemplateSchedule).all()
        logger.info(f"✓ Found {len(schedules)} template schedules")

        # Check templates
        templates = db.query(MessageTemplate).all()
        logger.info(f"✓ Found {len(templates)} message templates")

        # Check reservations
        reservations = db.query(Reservation).all()
        logger.info(f"✓ Found {len(reservations)} reservations")

        # Verify relationships
        for schedule in schedules:
            if schedule.template:
                logger.info(f"✓ Schedule '{schedule.schedule_name}' → Template '{schedule.template.name}'")
            else:
                logger.warning(f"✗ Schedule '{schedule.schedule_name}' has no template!")
                return False

        return True

    except Exception as e:
        logger.error(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def test_target_filtering():
    """Test target filtering logic"""
    logger.info("\n=== Testing Target Filtering ===")

    db = SessionLocal()
    try:
        executor = TemplateScheduleExecutor(db)

        # Test each schedule's target filtering
        schedules = db.query(TemplateSchedule).all()

        for schedule in schedules:
            logger.info(f"\nTesting: {schedule.schedule_name}")
            logger.info(f"  Date filter: {schedule.date_filter}")
            logger.info(f"  Exclude sent: {schedule.exclude_sent}")

            targets = executor.preview_targets(schedule)
            logger.info(f"  ✓ Filtered to {len(targets)} targets")

            if targets and len(targets) > 0:
                sample = targets[0]
                logger.info(f"  Sample: {sample['customer_name']} - Room: {sample.get('room_number', 'N/A')}")

        return True

    except Exception as e:
        logger.error(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


async def main():
    """Run all tests"""
    logger.info("=== Template Scheduling System Tests ===\n")

    tests = [
        ("Database Schema", test_database_schema),
        ("Target Filtering", test_target_filtering),
        ("Schedule Manager", test_schedule_manager),
        ("Template Executor", test_template_executor),
    ]

    results = {}

    for name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            results[name] = result
        except Exception as e:
            logger.error(f"Test '{name}' crashed: {e}")
            results[name] = False

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status} - {name}")

    logger.info(f"\nTotal: {passed}/{total} tests passed")
    logger.info("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
